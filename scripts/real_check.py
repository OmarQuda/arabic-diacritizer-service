"""Run sample sentences through a running service backed by a real provider.

Usage: uv run python scripts/real_check.py [base_url] [service_key] [delay_s]
The delay keeps free-tier keys under their requests-per-minute limit.
Reports how many outputs passed base-text validation, repair attempts and latency.
It does not score vowel accuracy; that needs a gold diacritized corpus.
"""

import statistics
import sys
import time

import httpx

SENTENCES = [
    "ذهب الولد إلى المدرسة",
    "كتب الطالب الدرس",
    "العلم نور",
    "يحب الأطفال اللعب في الحديقة",
    "قرأت الكتاب الذي أعطيتني إياه",
    "سافر أخي إلى الكويت في الصيف",
    "تشرق الشمس من الشرق",
    "اجتمع المعلمون في القاعة الكبيرة",
    "هل زرت المتحف الوطني؟",
    "إن الصبر مفتاح الفرج",
    "شرب الرجل كوبا من الماء",
    "تعلمت اللغة العربية منذ الصغر",
    "كانت المدينة هادئة في الليل",
    "يعمل المهندس على مشروع جديد",
    "أرسلت الشركة التقرير إلى العميل",
    "لا تؤجل عمل اليوم إلى الغد",
    "فتح التاجر دكانه في الصباح الباكر",
    "استمع الطلاب إلى المحاضرة باهتمام",
    "يسقط المطر بغزارة في الشتاء",
    "وصل القطار إلى المحطة متأخرا",
]


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8021"
    key = sys.argv[2] if len(sys.argv) > 2 else "dev-key"
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 13.0
    model = "unknown"
    valid, attempts, latencies, rejected = 0, [], [], []
    with httpx.Client(timeout=60) as client:
        for i, text in enumerate(SENTENCES, 1):
            if i > 1:
                time.sleep(delay)
            r = client.post(
                f"{base}/v1/diacritize",
                headers={"X-Service-Key": key},
                json={"text": text, "request_id": f"real-{i}"},
            )
            if r.status_code == 200 and r.json().get("valid"):
                body = r.json()
                valid += 1
                model = body["model"]
                attempts.append(body["attempts"])
                latencies.append(body["latency_ms"])
            else:
                rejected.append((i, r.status_code))
    print(f"model: {model}")
    print(f"valid: {valid}/{len(SENTENCES)}")
    print(f"needed a repair call: {sum(1 for a in attempts if a > 1)}")
    if latencies:
        print(f"latency ms: median {statistics.median(latencies):.0f}, max {max(latencies):.0f}")
    for i, status in rejected:
        print(f"rejected #{i}: HTTP {status}")


if __name__ == "__main__":
    main()
