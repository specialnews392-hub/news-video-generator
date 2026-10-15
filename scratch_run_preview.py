import urllib.request
import json
import time

payload = {
    "topic": "Внешняя политика России",
    "language": "ru",
    "voice_id": "ru-dmitry",
    "theme": "default",
    "voice_rate": "+0%",
    "target_length": 15000,
    "skip_image_analysis": True,
    "is_preview": True
}

req = urllib.request.Request(
    "http://localhost:8501/api/generate",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)

try:
    resp = urllib.request.urlopen(req)
    res_data = json.loads(resp.read().decode("utf-8"))
    job_id = res_data.get("job_id")
    print(f"Launched preview job: {job_id}")
    
    # Poll status until done
    for _ in range(60):
        time.sleep(2)
        status_resp = urllib.request.urlopen(f"http://localhost:8501/api/status/{job_id}")
        det = str(st.get('detail', '')).encode('ascii', 'replace').decode('ascii')
        stg = str(st.get('stage', '')).encode('ascii', 'replace').decode('ascii')
        print(f"[{job_id}] {st.get('progress')}% - {stg}: {det}")
        if st.get("status") in ["completed", "failed"]:
            print("Finished with status:", st.get("status"))
            if st.get("error"):
                print("Error details:", st.get("error"))
            break
except Exception as e:
    print("Error:", e)
