@echo off
REM Se déplacer dans le dossier du projet
cd /d "C:\Users\Belyazid\.cline\data\workspaces\chat\compta_ma"

REM Lancer l'application avec l'environnement virtuel
call .venv\Scripts\activate
uvicorn app.main:app --reload

REM Garder la fenêtre ouverte en cas d'erreur
pause