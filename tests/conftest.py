"""
Pytest configuration and fixtures for SDK v2 compatibility testing.
"""
import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

# Add sequences to path
sys.path.insert(0, str(Path(__file__).parent.parent / "sequences" / "stm32_firmware_upload"))

from station_service_sdk import ExecutionContext


@pytest.fixture
def temp_firmware_file(tmp_path):
    """Create a temporary firmware file for testing."""
    firmware_file = tmp_path / "test_firmware.bin"
    # Create a minimal valid binary file
    firmware_file.write_bytes(b'\x00' * 1024)
    return firmware_file


@pytest.fixture
def mock_programmer_path(tmp_path):
    """Create a mock STM32CubeProgrammer CLI."""
    import os
    programmer = tmp_path / "STM32_Programmer_CLI"
    programmer.write_text("#!/bin/bash\necho 'STM32CubeProgrammer version 2.17.0'\n")
    os.chmod(programmer, 0o755)
    return programmer


@pytest.fixture
def execution_context_factory():
    """Factory for creating ExecutionContext instances."""
    def _create(
        execution_id: str = "test-001",
        wip_id: str = "WIP-001",
        dry_run: bool = False,
        parameters: Dict[str, Any] = None
    ) -> ExecutionContext:
        return ExecutionContext(
            execution_id=execution_id,
            wip_id=wip_id,
            sequence_name="stm32_firmware_upload",
            sequence_version="1.0.0",
            hardware_config={},
            parameters=parameters or {},
            dry_run=dry_run
        )
    return _create


@pytest.fixture
def mock_subprocess():
    """Mock asyncio.create_subprocess_exec for CLI testing."""
    async def mock_communicate():
        return (
            b"STM32CubeProgrammer version 2.17.0\nDevice ID: 0x450\nDevice name: STM32H7xx",
            b""
        )

    mock_process = MagicMock()
    mock_process.communicate = mock_communicate
    mock_process.returncode = 0

    return mock_process
