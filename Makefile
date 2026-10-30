SOURCE_DIR = my_package
TEST_DIR = tests
PYTHON ?= python3

.PHONY: lint format venv install install-dev install-docs install-test build clean test tests tests-cov check dashboard-check ci

# code formatting and linting

lint:
	pylint ${SOURCE_DIR}

format:
	isort ${SOURCE_DIR}
	black ${SOURCE_DIR}

# installing

venv: # затем необходимо активировать: source .venv/bin/activate
	$(PYTHON) -m venv .venv

install: # простая установка зависимостей без editable режима
	$(PYTHON) -m pip install .

install-dev: # установка зависимостей для разработки
	$(PYTHON) -m pip install -e '.[dev]'

install-docs: # установка зависимостей для документации
	$(PYTHON) -m pip install -e '.[docs]'

install-test: # только пакет и тесты, без BlocksNet/PyTorch/Jupyter из research
	$(PYTHON) -m pip install -e '.[tests]'

# building the package

build:
	$(PYTHON) -m build .

clean:
	rm -rf ./build ./dist ./${SOURCE_DIR}.egg-info

# testing

test: tests

tests: # тестирование; test и tests поддерживаются для совместимости
	$(PYTHON) -m pytest ${TEST_DIR}

tests-cov: # тестирование с выводом процента покрытия кода тестами
	$(PYTHON) -m pytest ${TEST_DIR} --cov

check: # синтаксис и структура, без выполнения ноутбуков
	$(PYTHON) scripts/check_project.py

dashboard-check: # генерация только во временную папку из сохранённых результатов
	$(PYTHON) scripts/check_project.py --dashboard

ci: check test dashboard-check
