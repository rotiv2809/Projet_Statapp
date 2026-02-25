# Projet_Statapp
Create your own local data folder: data/... and so inside this folder, it consists of client.csv, dossier.csv, transaction.csv.

Requirement python version 3.12 

If you want to change version python
```
deactivate 2>/dev/null || true
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

Run scripts/build_sqlite_db.py
```
python3 scripts/build_sqlite_db.py \
  --client_csv data/client.csv \
  --dossier_csv data/dossier.csv \
  --transaction_csv data/transaction.csv \
  --sqlite data/statapp.sqlite
```

create virtual enviromment
```
python3 -m .venv venv
source .venv/bin/activate
```


You need to install your own requirements.txt in your virtual environment 
```

pip install -r requirements.txt

```

Adding environment variable:
```
cp .env.example .env
```

after having .env: 
-changing LLM_Provider and LLM_Model base on your model
-Filling your API's model.

To use ollama model: 
Go to the website
```
https://ollama.com/
```
For instance if you want to use model: sqlcoder then search it on the website.

In your terminal, please input:
```
ollama pull sqlcoder:7b
```
Then, it will download automatically. please waiting until it finishes.

On the other hand, the model generates by google or OpenAI. You need to have your own API. When you have it, please filling in .env (Not .env.example).

To test the frontend, in your terminal runs
```
streamlit run streamlit_app.py
```


Optional if you want to test function:
Testing database
```
sqlite3 data/statapp.sqlite ".tables"
sqlite3 data/statapp.sqlite "SELECT COUNT(*) FROM transactions;"
```

For testing sqlite, in Projet_statapp/ runs:

```
python -c "from app.db.sqlite import get_schema_text, run_query; print(get_schema_text('data/statapp.sqlite')); cols, rows = run_query('data/statapp.sqlite', 'SELECT COUNT(*) AS n FROM clients'); print(cols, rows)"
```


sqlite3 data/statapp.sqlite "SELECT COUNT(*) As nombre_transaction_cambodge
FROM transactions WHERE pays ='Cambodia' AND statut_transaction = 'VALIDE';"

For testing safety, in Projet_statapp/ runs in terminal:
```
python -c "from app.safety.sql_validator import validate_sql; 
print(validate_sql('SELECT prenom FROM clients LIMIT 1'));
print(validate_sql('SELECT date_naissance FROM clients LIMIT 1'));
print(validate_sql('SELECT client_id, commune FROM clients LIMIT 1'));"
```

Testing chatbot
```
 python -c "from app.db.sqlite import get_schema_text; \
from app.agents.sql_agent import SQLAgent; \
from app.safety.sql_validator import validate_sql; \
from app.pipeline.execute_sql import execute_sql; \
schema = get_schema_text('data/statapp.sqlite'); \
agent = SQLAgent(); \
q = 'How many clients are there by segment_client?'; \
sql = agent.generate_sql(q, schema); \
print('SQL:', sql); \
print('VALID:', validate_sql(sql)); \
print(execute_sql('data/statapp.sqlite', sql))"
```

```
Projet_Statapp/
  app/
    __init__.py
    config.py
    db/
      __init__.py
      sqlite.py
    prompts/
      __init__.py
      router.py
      sql.py
      gatekeeper.py
      summary.py
    safety/
      __init__.py
      sql_validator.py
    agents/
      __init__.py
      router_agent.py
      gatekeeper_agent.py
      sql_agent.py
      chat_agent.py   
    main.py          (CLI or FastAPI entry)
  benchmarks/
    benchmark_v0.csv
  scripts/
    build_sqlite_db.py   (keep yours)
    run_benchmark.py     (new)
  requirements.txt       
```

