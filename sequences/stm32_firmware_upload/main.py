"""CLI entry point for STM32 firmware upload sequence."""

import asyncio
import sys

# Fix for Windows asyncio compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from .sequence import STM32FirmwareUpload

if __name__ == "__main__":
    exit(STM32FirmwareUpload.run_from_cli())
