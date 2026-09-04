Demo Backend — işə salma
bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # sonra .env-də GOOGLE_API_KEY doldur
uvicorn main:app --reload

Yoxla: http://localhost:8000/docs → /research və /script-i buradan test et.

POST /research body: {"command":"Find the latest AI agent news and make a 45s video"}
POST /script body: {"topic":"Autonomous AI Agents","duration":45}

Model dəyişmək (arxitektura göstərişi): .env-də yalnız LLM_PROVIDER + LLM_MODEL dəyiş — kod dəyişmir.