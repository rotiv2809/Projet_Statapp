# Projet_Statapp
Create your own local data folder: data/... and so inside this folder, it consist of client.csv, dossier.csv, transaction.csv.


Run scripts/build_sqlite_db.py
```
python scripts/build_sqlite_db.py \
  --client_csv data/client.csv \
  --dossier_csv data/dossier.csv \
  --transaction_csv data/transaction.csv \
  --sqlite data/statapp.sqlite
```

Testing database
```
sqlite3 data/statapp.sqlite ".tables"
sqlite3 data/statapp.sqlite "SELECT COUNT(*) FROM transactions;"
```
