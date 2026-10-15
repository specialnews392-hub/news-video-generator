import urllib.request
import json
import time

for _ in range(40):
    try:
        resp = urllib.request.urlopen("http://localhost:8501/api/status/07ff7e80")
        d = json.loads(resp.read().decode("utf-8"))
        prog = d.get("progress")
        stat = d.get("status")
        det = str(d.get("detail", ""))[:60]
        print(f"Progress: {prog}%, Status: {stat}, Detail: {det}")
        if stat in ["completed", "failed"]:
            print("DONE! Video:", d.get("video_filename"), "Error:", d.get("error"))
            break
    except Exception as e:
        print("Poll error:", e)
    time.sleep(3)
