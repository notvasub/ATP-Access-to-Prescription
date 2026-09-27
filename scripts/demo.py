"""Run ATP and a temporary HTTPS tunnel. Ctrl+C cleans up both processes."""

import asyncio
import os
import re
import shutil
import signal
import sys

import httpx

from atp.config import ROOT, Settings


async def main():
    s = Settings()
    binary = shutil.which("cloudflared") or str(ROOT / ".local/bin/cloudflared")
    if not os.path.isfile(binary):
        raise SystemExit(
            "Install cloudflared from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ and retry."
        )
    if not (ROOT / "web/dist/index.html").exists():
        raise SystemExit("Run make setup first.")
    processes = []
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    public_path = ROOT / ".local/public-url"
    public_path.unlink(missing_ok=True)
    url = f"http://127.0.0.1:{s.app_port}"
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            try:
                r = await client.get(url + "/api/health")
                running = r.status_code == 200 and r.json().get("product") == "ATP"
            except (httpx.HTTPError, ValueError):
                running = False
        if not running:
            server = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "uvicorn",
                "atp.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(s.app_port),
                "--no-access-log",
                cwd=ROOT,
            )
            processes.append(server)
            for _ in range(60):
                async with httpx.AsyncClient(timeout=1) as client:
                    try:
                        (await client.get(url + "/api/health")).raise_for_status()
                        break
                    except httpx.HTTPError:
                        await asyncio.sleep(0.25)
            else:
                raise RuntimeError("Backend did not become ready")
        print(f"Local workspace: {url}", flush=True)
        tunnel = await asyncio.create_subprocess_exec(
            binary,
            "tunnel",
            "--url",
            url,
            "--no-autoupdate",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=ROOT,
        )
        processes.append(tunnel)

        async def output():
            async for line in tunnel.stdout:
                text = line.decode(errors="replace")
                match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
                if match:
                    public_path.write_text(match.group())
                    print(
                        f"Phone / presentation URL: {match.group()}\nOpen the workspace, start a call, then Invite your team for QR links.\nKeep this terminal running. Ctrl+C stops the tunnel.",
                        flush=True,
                    )
            stopped.set()

        reader = asyncio.create_task(output())
        await stopped.wait()
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
    finally:
        public_path.unlink(missing_ok=True)
        for process in reversed(processes):
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 10)
                except TimeoutError:
                    process.kill()
                    await process.wait()


if __name__ == "__main__":
    asyncio.run(main())
