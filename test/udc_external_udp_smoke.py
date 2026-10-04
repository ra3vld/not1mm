"""Send real host UDP into an installed Flatpak; application permissions apply."""

import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from udc_runtime_fixture import udp_packet

APP = "io.github.mbridak.not1mm.UdcTest"
root = Path(tempfile.mkdtemp(prefix="not1mm-external-udp-"))
ready = root / "ready.json"
log = root / "application.log"
script = Path(__file__).with_name("udc_runtime_qt_smoke.py").resolve()
sent = 0
with (
    log.open("w") as output,
    socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender,
):
    process = subprocess.Popen(
        [
            "flatpak",
            "run",
            "--filesystem=/tmp",
            "--env=QT_QPA_PLATFORM=offscreen",
            "--env=UDC_UDP_READY=" + str(ready),
            "--command=python3",
            APP,
            str(script),
        ],
        stdout=output,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 120
    try:
        while process.poll() is None and time.monotonic() < deadline:
            if ready.exists():
                data = json.loads(ready.read_text())
                if data["sequence"] > sent:
                    sender.sendto(
                        udp_packet(data["record"]), ("127.0.0.1", data["port"])
                    )
                    sent = data["sequence"]
                    ready.with_suffix(".sent").write_text(str(sent))
            time.sleep(0.05)
        if process.poll() is None:
            raise AssertionError("Installed Flatpak external UDP test timed out")
        assert process.returncode == 0, log.read_text()[-4000:]
        assert sent == 6, sent
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
text = log.read_text()
report = next(
    json.loads(line) for line in text.splitlines() if line.startswith('{"status":')
)
assert report["source"].startswith("/app/"), report
report.update(external_packets=sent, host_log=str(log))
print(json.dumps(report), flush=True)
