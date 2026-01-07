"""
SDK v2 Compatibility Tests for STM32 Firmware Upload Sequence.

Tests verify:
1. SDK imports work correctly
2. SequenceBase lifecycle methods function properly
3. emit_* methods produce expected output
4. Error handling with SDK exceptions
5. Dry-run simulation with SequenceSimulator
"""
import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from io import StringIO

sys.path.insert(0, str(Path(__file__).parent.parent / "sequences" / "stm32_firmware_upload"))


class TestSDKImports:
    """Test SDK v2 import compatibility."""

    def test_basic_imports(self):
        """Test that all required SDK classes can be imported."""
        from station_service_sdk import (
            SequenceBase,
            RunResult,
            SetupError,
            HardwareError,
        )
        assert SequenceBase is not None
        assert RunResult is not None
        assert SetupError is not None
        assert HardwareError is not None

    def test_sequence_class_import(self):
        """Test that the sequence class can be imported."""
        from sequence import STM32FirmwareUpload
        assert STM32FirmwareUpload is not None
        assert STM32FirmwareUpload.name == "stm32_firmware_upload"
        assert STM32FirmwareUpload.version == "1.0.0"

    def test_sdk_v2_new_imports(self):
        """Test SDK v2 specific imports."""
        from station_service_sdk import (
            ExecutionContext,
            SequenceSimulator,
            SequenceLoader,
            MockHardware,
        )
        assert ExecutionContext is not None
        assert SequenceSimulator is not None
        assert SequenceLoader is not None
        assert MockHardware is not None


class TestSequenceInstantiation:
    """Test sequence instantiation with SDK v2."""

    def test_create_with_context(self, execution_context_factory, temp_firmware_file, mock_programmer_path):
        """Test sequence can be created with ExecutionContext."""
        from sequence import STM32FirmwareUpload

        context = execution_context_factory(
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        seq = STM32FirmwareUpload(
            context=context,
            hardware_config={},
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        assert seq.name == "stm32_firmware_upload"
        assert seq.context.execution_id == "test-001"

    def test_create_dry_run_mode(self, execution_context_factory, temp_firmware_file):
        """Test sequence in dry-run mode."""
        from sequence import STM32FirmwareUpload

        context = execution_context_factory(
            dry_run=True,
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": "/mock/path"
            }
        )

        seq = STM32FirmwareUpload(
            context=context,
            hardware_config={},
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": "/mock/path"
            }
        )

        assert seq.context.dry_run is True


class TestLifecycleMethods:
    """Test sequence lifecycle methods with SDK v2."""

    @pytest.mark.asyncio
    async def test_setup_success(self, execution_context_factory, temp_firmware_file, mock_programmer_path):
        """Test successful setup phase."""
        from sequence import STM32FirmwareUpload

        context = execution_context_factory(
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        seq = STM32FirmwareUpload(
            context=context,
            hardware_config={},
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        # Mock the programmer validation
        with patch.object(seq, '_validate_programmer', new_callable=AsyncMock) as mock_validate:
            await seq.setup()
            mock_validate.assert_called_once()

        assert seq.firmware_path == str(temp_firmware_file)
        assert seq.programmer_path == str(mock_programmer_path)

    @pytest.mark.asyncio
    async def test_setup_missing_firmware(self, execution_context_factory):
        """Test setup fails with missing firmware."""
        from sequence import STM32FirmwareUpload
        from station_service_sdk import SetupError

        context = execution_context_factory(
            parameters={
                "firmware_path": "/nonexistent/firmware.bin",
                "programmer_path": "/mock/path"
            }
        )

        seq = STM32FirmwareUpload(
            context=context,
            hardware_config={},
            parameters={
                "firmware_path": "/nonexistent/firmware.bin",
                "programmer_path": "/mock/path"
            }
        )

        with pytest.raises(SetupError) as exc_info:
            await seq.setup()

        assert "Firmware file not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_teardown_always_succeeds(self, execution_context_factory, temp_firmware_file, mock_programmer_path):
        """Test teardown completes even after errors."""
        from sequence import STM32FirmwareUpload

        context = execution_context_factory(
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        seq = STM32FirmwareUpload(
            context=context,
            hardware_config={},
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        # Mock check_stlink_connection
        with patch.object(seq, '_check_stlink_connection', new_callable=AsyncMock) as mock_check:
            mock_check.return_value = (False, {})
            await seq.teardown()

        # Should not raise any exceptions


class TestEmitMethods:
    """Test SDK emit methods work correctly."""

    @pytest.mark.asyncio
    async def test_emit_log(self, execution_context_factory, temp_firmware_file, mock_programmer_path, capsys):
        """Test emit_log produces JSON output."""
        from sequence import STM32FirmwareUpload

        context = execution_context_factory(
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        seq = STM32FirmwareUpload(
            context=context,
            hardware_config={},
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        seq.emit_log("info", "Test log message")

        captured = capsys.readouterr()
        assert '"type": "log"' in captured.out
        assert '"message": "Test log message"' in captured.out


class TestSequenceSimulator:
    """Test SequenceSimulator with SDK v2."""

    @pytest.mark.asyncio
    async def test_dry_run_simulation(self, temp_firmware_file):
        """Test dry-run simulation via SequenceSimulator."""
        from station_service_sdk import SequenceSimulator, SequenceLoader

        loader = SequenceLoader(str(Path(__file__).parent.parent / "sequences"))
        simulator = SequenceSimulator(loader)

        result = await simulator.dry_run(
            sequence_name="stm32_firmware_upload",
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": "/mock/programmer"
            }
        )

        assert isinstance(result, dict)
        assert "status" in result
        assert "steps" in result
        assert "logs" in result

    @pytest.mark.asyncio
    async def test_discover_packages(self):
        """Test SequenceLoader can discover packages."""
        from station_service_sdk import SequenceLoader

        loader = SequenceLoader(str(Path(__file__).parent.parent / "sequences"))
        packages = await loader.discover_packages()

        assert "stm32_firmware_upload" in packages

    @pytest.mark.asyncio
    async def test_load_manifest(self):
        """Test SequenceLoader can load manifest."""
        from station_service_sdk import SequenceLoader

        loader = SequenceLoader(str(Path(__file__).parent.parent / "sequences"))
        manifest = await loader.load_package("stm32_firmware_upload")

        assert manifest.name == "stm32_firmware_upload"
        assert manifest.version is not None


class TestErrorHandling:
    """Test error handling with SDK v2 exceptions."""

    @pytest.mark.asyncio
    async def test_hardware_error(self, execution_context_factory, temp_firmware_file, mock_programmer_path):
        """Test HardwareError is raised correctly."""
        from sequence import STM32FirmwareUpload
        from station_service_sdk import HardwareError

        context = execution_context_factory(
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        seq = STM32FirmwareUpload(
            context=context,
            hardware_config={},
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        # Mock setup and run that fails with HardwareError
        with patch.object(seq, '_validate_programmer', new_callable=AsyncMock):
            await seq.setup()

        with patch.object(seq, '_check_stlink_connection', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = HardwareError("ST-LINK connection failed")

            result = await seq.run()
            assert result["passed"] is False

    def test_setup_error_attributes(self):
        """Test SetupError has expected attributes."""
        from station_service_sdk import SetupError

        error = SetupError("Test error message")
        assert str(error) == "[SETUP_ERROR] Test error message"


class TestRunResult:
    """Test RunResult return type compatibility."""

    @pytest.mark.asyncio
    async def test_run_result_structure(self, execution_context_factory, temp_firmware_file, mock_programmer_path):
        """Test run() returns proper RunResult structure."""
        from sequence import STM32FirmwareUpload

        context = execution_context_factory(
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        seq = STM32FirmwareUpload(
            context=context,
            hardware_config={},
            parameters={
                "firmware_path": str(temp_firmware_file),
                "programmer_path": str(mock_programmer_path)
            }
        )

        # Mock all operations
        with patch.object(seq, '_validate_programmer', new_callable=AsyncMock):
            await seq.setup()

        with patch.object(seq, '_check_stlink_connection', new_callable=AsyncMock) as mock_conn, \
             patch.object(seq, '_upload_firmware', new_callable=AsyncMock) as mock_upload:

            mock_conn.return_value = (True, {"serial": "TEST123", "device_name": "STM32H7xx"})
            mock_upload.return_value = (True, 1.5, True)  # success, time, verify_success

            result = await seq.run()

        # Verify RunResult structure
        assert isinstance(result, dict)
        assert "passed" in result
        assert "measurements" in result
        assert isinstance(result["passed"], bool)
        assert isinstance(result["measurements"], dict)
