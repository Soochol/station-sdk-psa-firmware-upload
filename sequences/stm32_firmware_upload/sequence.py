"""
STM32 Firmware Upload Sequence

ST-LINK를 사용하여 STM32 MCU에 펌웨어를 업로드하는 시퀀스.
STM32CubeProgrammer CLI를 활용합니다.

Usage:
    uv run python -m stm32_firmware_upload.main --start --config-file config.json
"""

import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, Any

from station_service_sdk import (
    SequenceBase,
    RunResult,
    SetupError,
    HardwareError,
)


class STM32FirmwareUpload(SequenceBase):
    """STM32 펌웨어 업로드 시퀀스"""

    name = "stm32_firmware_upload"
    version = "1.0.0"
    description = "ST-LINK를 사용한 STM32 펌웨어 업로드"

    # STM32CubeProgrammer CLI 경로
    DEFAULT_PROGRAMMER_PATH = "/opt/st/stm32cubeclt_1.20.0/STM32CubeProgrammer/bin/STM32_Programmer_CLI"

    async def setup(self) -> None:
        """하드웨어 초기화 및 검증"""
        self.emit_log("info", "Initializing STM32 firmware upload sequence...")

        # 파라미터 로드
        self.firmware_path = self.get_parameter("firmware_path")
        self.programmer_path = self.get_parameter(
            "programmer_path",
            self.DEFAULT_PROGRAMMER_PATH
        )
        self.erase_before_upload = self.get_parameter("erase", False)  # 양산: False (자동 섹터 지우기)
        self.verify_after_upload = self.get_parameter("verify", True)
        self.reset_after_upload = self.get_parameter("reset", True)
        self.connection_mode = self.get_parameter("connection_mode", "swd")
        self.start_address = self.get_parameter("start_address", "0x08000000")
        self.stop_on_failure = self.get_parameter("stop_on_failure", True)

        # ST-LINK 연결 옵션 (양산용)
        self.connect_mode = self.get_parameter("connect_mode", "HOTPLUG")  # HOTPLUG(양산), NORMAL, UR
        self.reset_mode = self.get_parameter("reset_mode", "HWrst")  # HWrst, SWrst, Crst
        self.frequency = self.get_parameter("frequency", 4000)  # kHz

        # 펌웨어 파일 검증
        if not self.firmware_path:
            raise SetupError("firmware_path parameter is required")

        firmware_file = Path(self.firmware_path)
        if not firmware_file.exists():
            raise SetupError(f"Firmware file not found: {self.firmware_path}")

        if not firmware_file.suffix.lower() in ['.bin', '.hex', '.elf']:
            raise SetupError(f"Unsupported firmware format: {firmware_file.suffix}")

        self.firmware_size = firmware_file.stat().st_size
        self.emit_log("info", f"Firmware file: {self.firmware_path} ({self.firmware_size} bytes)")

        # STM32CubeProgrammer CLI 검증
        await self._validate_programmer()

        self.emit_log("info", "Setup completed successfully")

    async def run(self) -> RunResult:
        """펌웨어 업로드 실행"""
        # 스텝 수 계산: 연결확인 + (지우기?) + 업로드 + (검증?)
        total_steps = 2  # 연결확인 + 업로드
        if self.erase_before_upload:
            total_steps += 1
        if self.verify_after_upload:
            total_steps += 1

        passed = True
        measurements: Dict[str, Any] = {}
        stopped_at: Optional[str] = None
        current_step = 0

        # Step: ST-LINK 연결 확인
        current_step += 1
        self.check_abort()
        self.emit_step_start("check_connection", current_step, total_steps, "ST-LINK 연결 확인")
        step_start = time.time()

        try:
            connected, stlink_info = await self._check_stlink_connection()
            if not connected:
                raise HardwareError("ST-LINK not detected")

            self.emit_log("info", f"ST-LINK detected: {stlink_info}")
            self.emit_step_complete("check_connection", current_step, True, time.time() - step_start)
        except Exception as e:
            self.emit_error("CONNECTION_ERROR", str(e))
            self.emit_step_complete("check_connection", current_step, False, time.time() - step_start, error=str(e))
            if self.stop_on_failure:
                return {"passed": False, "measurements": measurements, "data": {"stopped_at": "check_connection"}}
            passed = False
            stopped_at = "check_connection"

        # Step: 칩 지우기 (Erase) - 옵션
        if self.erase_before_upload and (passed or not self.stop_on_failure):
            current_step += 1
            self.check_abort()
            self.emit_step_start("erase_chip", current_step, total_steps, "플래시 메모리 지우기")
            step_start = time.time()

            try:
                erase_success = await self._erase_flash()
                if not erase_success:
                    raise HardwareError("Failed to erase flash memory")

                self.emit_step_complete("erase_chip", current_step, True, time.time() - step_start)
            except Exception as e:
                self.emit_error("ERASE_ERROR", str(e))
                self.emit_step_complete("erase_chip", current_step, False, time.time() - step_start, error=str(e))
                if self.stop_on_failure:
                    return {"passed": False, "measurements": measurements, "data": {"stopped_at": "erase_chip"}}
                passed = False
                stopped_at = stopped_at or "erase_chip"

        # Step: 펌웨어 업로드 (검증 옵션 포함)
        verify_result = False
        if passed or not self.stop_on_failure:
            current_step += 1
            self.check_abort()
            self.emit_step_start("upload_firmware", current_step, total_steps, "펌웨어 업로드")
            step_start = time.time()

            try:
                # 업로드 시 검증도 함께 수행 (-v 옵션)
                upload_success, upload_time, verify_result = await self._upload_firmware(
                    verify=self.verify_after_upload
                )
                if not upload_success:
                    raise HardwareError("Failed to upload firmware")

                self.emit_step_complete("upload_firmware", current_step, True, time.time() - step_start)
            except Exception as e:
                self.emit_error("UPLOAD_ERROR", str(e))
                self.emit_step_complete("upload_firmware", current_step, False, time.time() - step_start, error=str(e))
                if self.stop_on_failure:
                    return {"passed": False, "measurements": measurements, "data": {"stopped_at": "upload_firmware"}}
                passed = False
                stopped_at = stopped_at or "upload_firmware"

        # Step: 검증 결과 보고 (업로드 시 이미 수행됨)
        if self.verify_after_upload and (passed or not self.stop_on_failure):
            current_step += 1
            self.check_abort()
            self.emit_step_start("verify_firmware", current_step, total_steps, "펌웨어 검증")
            step_start = time.time()

            if verify_result:
                self.emit_step_complete("verify_firmware", current_step, True, time.time() - step_start)
            else:
                self.emit_error("VERIFY_ERROR", "Firmware verification failed")
                self.emit_step_complete("verify_firmware", current_step, False, time.time() - step_start, error="Firmware verification failed")
                passed = False
                stopped_at = stopped_at or "verify_firmware"

        # 리셋 (선택적)
        if self.reset_after_upload and passed:
            self.check_abort()
            try:
                await self._reset_target()
                self.emit_log("info", "Target reset completed")
            except Exception as e:
                self.emit_log("warning", f"Reset failed: {e}")

        result: RunResult = {
            "passed": passed,
            "measurements": measurements,
        }
        if stopped_at:
            result["data"] = {"stopped_at": stopped_at}

        return result

    async def teardown(self) -> None:
        """정리 작업"""
        self.emit_log("info", "Cleaning up...")

        # 이전 단계 에러 확인 및 진단 정보 수집
        if self.last_error:
            self.emit_log("warning", f"이전 단계에서 에러 발생: {self.last_error}")

            # 실패 시 ST-LINK 상태 재확인
            try:
                connected, info = await self._check_stlink_connection()
                if connected:
                    self.emit_log("debug", f"ST-LINK 상태: 연결됨 - {info.get('serial', 'unknown')}")
                else:
                    self.emit_log("debug", "ST-LINK 상태: 연결 끊김")
            except Exception as e:
                self.emit_log("debug", f"ST-LINK 상태 확인 실패: {e}")

        # ST-LINK 연결 해제는 CLI가 자동으로 처리
        self.emit_log("info", "Teardown completed")

    # =========================================================================
    # Private Methods
    # =========================================================================

    # 일반적인 STM32CubeProgrammer 설치 경로들
    COMMON_PROGRAMMER_PATHS = [
        "/opt/st/stm32cubeclt_1.20.0/STM32CubeProgrammer/bin/STM32_Programmer_CLI",
        "/opt/st/stm32cubeide_1.17.0/plugins/com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer.linux64_2.2.100.202406141446/tools/bin/STM32_Programmer_CLI",
        "/usr/local/STMicroelectronics/STM32Cube/STM32CubeProgrammer/bin/STM32_Programmer_CLI",
        "/opt/STM32CubeProgrammer/bin/STM32_Programmer_CLI",
        # Windows paths
        "C:/Program Files/STMicroelectronics/STM32Cube/STM32CubeProgrammer/bin/STM32_Programmer_CLI.exe",
        "C:/ST/STM32CubeCLT/STM32CubeProgrammer/bin/STM32_Programmer_CLI.exe",
    ]

    async def _validate_programmer(self) -> None:
        """STM32CubeProgrammer CLI 설치 검증"""
        programmer_path = Path(self.programmer_path)

        # 1. 지정된 경로 확인
        if not programmer_path.exists():
            # 대안 경로 검색
            found_path = None
            for alt_path in self.COMMON_PROGRAMMER_PATHS:
                if Path(alt_path).exists():
                    found_path = alt_path
                    break

            error_msg = f"STM32CubeProgrammer CLI not found: {self.programmer_path}"

            if found_path:
                error_msg += f"\n\n  Found at alternative location: {found_path}"
                error_msg += f"\n  Update 'programmer_path' parameter to use this path."
            else:
                error_msg += "\n\n  STM32CubeProgrammer is not installed."
                error_msg += "\n  Please install STM32CubeCLT or STM32CubeProgrammer:"
                error_msg += "\n  - Download: https://www.st.com/en/development-tools/stm32cubeprog.html"
                error_msg += "\n  - Linux: Install to /opt/st/ or /usr/local/STMicroelectronics/"
                error_msg += "\n  - After installation, set 'programmer_path' parameter correctly."

            raise SetupError(error_msg)

        # 2. 실행 권한 확인 (Linux/macOS)
        import os
        if os.name != 'nt' and not os.access(programmer_path, os.X_OK):
            raise SetupError(
                f"STM32CubeProgrammer CLI is not executable: {self.programmer_path}\n"
                f"  Run: chmod +x {self.programmer_path}"
            )

        # 3. 실제 실행 가능 여부 확인 (버전 출력 테스트)
        try:
            process = await asyncio.create_subprocess_exec(
                str(programmer_path), "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
            output = stdout.decode() + stderr.decode()

            if "STM32CubeProgrammer" in output or process.returncode == 0:
                # 버전 정보 추출 시도
                for line in output.split("\n"):
                    if "version" in line.lower() or "STM32CubeProgrammer" in line:
                        self.emit_log("info", f"Programmer: {line.strip()}")
                        break
                else:
                    self.emit_log("info", f"STM32CubeProgrammer CLI verified: {self.programmer_path}")
            else:
                raise SetupError(
                    f"STM32CubeProgrammer CLI failed to execute:\n{output}"
                )
        except asyncio.TimeoutError:
            raise SetupError("STM32CubeProgrammer CLI timed out during version check")
        except FileNotFoundError:
            raise SetupError(
                f"STM32CubeProgrammer CLI not found or missing dependencies: {self.programmer_path}\n"
                "  Check if all required libraries are installed."
            )
        except Exception as e:
            raise SetupError(f"Failed to verify STM32CubeProgrammer CLI: {e}")

    def _build_connect_args(self) -> str:
        """ST-LINK 연결 인자 문자열 생성"""
        # 기본: port=SWD
        connect_str = f"port={self.connection_mode.upper()}"

        # 연결 모드 (NORMAL, HOTPLUG, UR)
        if self.connect_mode and self.connect_mode.upper() != "NORMAL":
            connect_str += f" mode={self.connect_mode.upper()}"

        # 리셋 모드 (HWrst, SWrst, Crst)
        if self.reset_mode:
            connect_str += f" reset={self.reset_mode}"

        # 통신 속도 (kHz)
        if self.frequency:
            connect_str += f" freq={self.frequency}"

        return connect_str

    async def _run_programmer_cmd(self, args: list) -> tuple[bool, str]:
        """STM32CubeProgrammer CLI 명령 실행"""
        cmd = [self.programmer_path] + args
        self.emit_log("debug", f"Running: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120  # 2분 타임아웃
            )

            output = stdout.decode() + stderr.decode()
            success = process.returncode == 0

            if not success:
                self.emit_log("error", f"Command failed: {output}")

            return success, output
        except asyncio.TimeoutError:
            raise HardwareError("Programmer command timed out")
        except Exception as e:
            raise HardwareError(f"Failed to run programmer: {e}")

    async def _check_stlink_connection(self) -> tuple[bool, dict]:
        """ST-LINK 연결 상태 확인"""
        _, output = await self._run_programmer_cmd(["-c", self._build_connect_args(), "-l"])

        # Device ID가 출력에 있으면 MCU 연결된 것으로 판단
        # (CLI가 -l 옵션에서 exit code 0을 반환하지 않을 수 있음)
        if "Device ID" in output or "Device name" in output:
            # 시리얼 번호 추출 시도
            serial = "unknown"
            device_name = "unknown"
            for line in output.split("\n"):
                if "ST-LINK SN" in line:
                    parts = line.split(":")
                    if len(parts) > 1:
                        serial = parts[1].strip()
                if "Device name" in line:
                    parts = line.split(":")
                    if len(parts) > 1:
                        device_name = parts[1].strip()

            return True, {"serial": serial, "device_name": device_name}

        return False, {}

    async def _erase_flash(self) -> bool:
        """플래시 메모리 전체 삭제"""
        success, _ = await self._run_programmer_cmd([
            "-c", self._build_connect_args(),
            "-e", "all"
        ])
        return success

    async def _upload_firmware(self, verify: bool = False) -> tuple[bool, float, bool]:
        """펌웨어 업로드 (선택적 검증 포함)

        Args:
            verify: True이면 업로드 후 검증 수행

        Returns:
            (upload_success, upload_time, verify_success)
        """
        start_time = time.time()

        args = [
            "-c", self._build_connect_args(),
            "-w", self.firmware_path,
            self.start_address,
        ]

        # -v 옵션은 -w 바로 뒤에 붙여야 함
        if verify:
            args.append("-v")

        success, output = await self._run_programmer_cmd(args)
        upload_time = time.time() - start_time

        # 검증 결과 확인
        verify_success = False
        if verify and success:
            verify_success = "File download complete" in output or "Download verified successfully" in output
        elif verify:
            # 업로드는 성공했지만 검증 실패 체크
            verify_success = "Download verified successfully" in output

        return success, upload_time, verify_success if verify else True

    async def _reset_target(self) -> bool:
        """타겟 리셋"""
        success, _ = await self._run_programmer_cmd([
            "-c", self._build_connect_args(),
            "-rst"
        ])
        return success


