# API contract (shared by backend and UI; do not change without the manager)

Service: FastAPI, Arabic diacritization worker. Bind 127.0.0.1:8020 by default (HOST/PORT env).
Auth: header `X-Service-Key` on /v1/* routes. Accepts SERVICE_KEY (current) or SERVICE_KEY_PREVIOUS, compared in constant time. Dev default in .env.example: SERVICE_KEY=dev-key.

GET  /                 -> static/index.html (the UI; no auth)
GET  /health/live      -> 200 {"status":"ok"}
GET  /health/ready     -> 200 {"status":"ready","fake_provider":bool,"provider":str,"model":str} (no paid call)
POST /v1/diacritize    body {"text": str, "request_id"?: str, "simulate"?: "added_word"|"removed_word"|"translation"|"markdown"}
                       (`simulate` only honoured when FAKE_PROVIDER=1: the fake model returns that kind of bad output, to show the checker)
  200 {"request_id","input","output","valid":true,"attempts":int,"provider","model",
       "usage":{"prompt_tokens":int,"completion_tokens":int,"cost_usd":float},"latency_ms":int}
  401 {"error":"unauthorized"}
  422 {"error":"validation_failed","reason":"added_words|removed_words|changed_letters|markdown|json|empty","attempts":int,"detail":str}
  413 {"error":"text_too_long","max_chars":int}
  502 {"error":"provider_error","detail":str}   504 {"error":"provider_timeout"}
POST /v1/corrections   body {"request_id"?: str, "input": str, "model_output": str, "corrected": str, "note"?: str}
  201 {"id":int,"created_at":iso8601,"request_id","diacritics_changed":int}
  422 {"error":"invalid_correction","reason":"base_text_mismatch"}   (corrected must equal input once diacritics are stripped)
GET  /v1/corrections?limit=20 -> 200 {"items":[{"id","created_at","request_id","input","model_output","corrected","note","diacritics_changed"}]}
