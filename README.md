<div align="center">

# CryptoLayer Web UI

<img src="static/images/logo_alt.svg" alt="CLWU" width="300">


Web-интерфейс для защищенного обмена сообщениями в мессенджерах на базе CryptoLayer.

[![License](https://img.shields.io/badge/License-MIT-brightgreen?color=blue&style=flat)](LICENSE)
[![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54&style=flat-square)](https://www.python.org/)



---

<img src="stuff/screenshot1.png" width="500"> <img src="stuff/screenshot2.png" width="500">

</div>

## Запуск:

```shell
git submodule update --init --recursive

python3 -m venv venv

source venv/bin/activate

python3 src/modules/generate_reqs.py

pip install -r src/modules/common_requirements.txt

pip install -r requirements.txt

python3 src/modules/generate_hidden_imports.py

cd src

uvicorn main:app --host 0.0.0.0 --port 8000
```

###### (Или запустить run.sh)

- открыть в браузере http://127.0.0.1:8000/




## Ссылки

<a id="crypto-ref"></a>1 - CryptoLayer: https://github.com/igmunv/cryptolayer </a>

<a id="modules-ref"></a>2 - Модули: https://github.com/igmunv/cryptolayer-modules </a>