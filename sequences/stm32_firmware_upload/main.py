"""CLI entry point for STM32 firmware upload sequence."""

from .sequence import STM32FirmwareUpload

if __name__ == "__main__":
    exit(STM32FirmwareUpload.run_from_cli())
