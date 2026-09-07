"""Esporta in CSV lo storico di allenamento reale di Lorenzo da Overload (Supabase).

I CSV finiscono in `data/overload-real/`, che è fuori dal versionamento: sono dati
personali e il repo d'esame è pubblico. Il formato prodotto qui è il **formato di
riferimento** dell'import CSV di Progressive.

Credenziali: nessuna nel repo. Il token di accesso è quello della Supabase CLI, letto
dal portachiavi di macOS, quindi serve `supabase login` fatto una volta sola. Si usa
l'endpoint SQL della Management API invece di `supabase db dump` perché quest'ultimo
richiede Docker, che qui non gira.

    python3 scripts/export_overload.py
"""

import csv
import json
import os
import subprocess

PROJECT_REF = "wgvbbkivpnezbxmkvsou"  # progetto Supabase "Overload-Database"
USER_ID = "a4573675-dbf6-4b24-a4e9-4abfa98573fa"  # l'account di Lorenzo
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "overload-real")

# Overload è pubblica sull'App Store: il DB contiene anche altri account (a oggi vuoti).
# Ogni query filtra su USER_ID — senza quel filtro l'export prenderebbe dati di estranei.
TABLES = {
    "profiles": "select * from profiles where id = '{u}' order by created_at",
    "exercises": "select * from exercises where user_id = '{u}' order by created_at",
    "routines": "select * from routines where user_id = '{u}' order by created_at",
    "routine_exercises": (
        "select re.* from routine_exercises re join routines r on r.id = re.routine_id "
        "where r.user_id = '{u}' order by re.routine_id, re.position"
    ),
    "workout_sessions": "select * from workout_sessions where user_id = '{u}' order by started_at",
    "session_sets": (
        "select s.* from session_sets s join workout_sessions w on w.id = s.session_id "
        "where w.user_id = '{u}' order by w.started_at, s.exercise_id, s.set_number"
    ),
}


def access_token():
    return subprocess.run(
        ["security", "find-generic-password", "-s", "Supabase CLI", "-w"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def query(sql, token):
    """Esegue SQL sul progetto e restituisce le righe come lista di dict."""
    body = json.dumps({"query": sql})
    out = subprocess.run(
        [
            "curl", "-sS", "-X", "POST",
            f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query",
            "-H", f"Authorization: Bearer {token}",
            "-H", "Content-Type: application/json",
            "--data-binary", "@-",
        ],
        input=body, capture_output=True, text=True, check=True,
    ).stdout
    rows = json.loads(out)
    if isinstance(rows, dict):  # l'API risponde con un oggetto solo in caso d'errore
        raise RuntimeError(f"Supabase: {rows}")
    return rows


def cell(value):
    """Normalizza i tipi Postgres in testo CSV: booleani minuscoli, jsonb come JSON."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, separators=(",", ":"))
    return value


def main():
    token = access_token()
    os.makedirs(OUT_DIR, exist_ok=True)
    for table, sql in TABLES.items():
        # Le colonne vengono da information_schema, non dalla prima riga: così l'ordine
        # è quello del DB ed è stabile anche se una tabella tornasse vuota.
        columns = [
            row["column_name"]
            for row in query(
                "select column_name from information_schema.columns "
                f"where table_schema = 'public' and table_name = '{table}' "
                "order by ordinal_position",
                token,
            )
        ]
        rows = query(sql.format(u=USER_ID), token)
        path = os.path.join(OUT_DIR, f"{table}.csv")
        with open(path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({column: cell(row.get(column)) for column in columns})
        print(f"{table}.csv: {len(rows)} righe, {len(columns)} colonne")


if __name__ == "__main__":
    main()
