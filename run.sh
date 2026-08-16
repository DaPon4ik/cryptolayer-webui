git submodule update --init --recursive

python3 -m venv venv

source venv/bin/activate

python3 src/modules/generate_reqs.py

pip install -r src/modules/common_requirements.txt

pip install -r requirements.txt

python3 src/modules/generate_hidden_imports.py

cd src

uvicorn main:app --host 0.0.0.0 --port 8000