# Shared settings for the step scripts. Sourced, not run.
MUSIC_DIR="/volume1/musica/Music server/iTunes"
PYTHON="${PYTHON:-python3}"

cd "$(dirname "$0")" || exit 1
"$PYTHON" -c "import mutagen" 2>/dev/null || { echo "mutagen missing: $PYTHON -m pip install --user -r requirements.txt" >&2; exit 1; }
