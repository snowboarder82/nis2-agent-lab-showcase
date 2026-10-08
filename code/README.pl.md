# Kod

[English](README.md) · **Polski**

Te pliki są skopiowane bez zmian, bajt w bajt, z mojego prywatnego repozytorium laboratorium, z commita `892f75a1e07a42601a0a4dfc9ef1193a99bdadb6`: to merge modułu H11, 8 października 2026. Zachowują ścieżki z laboratorium, więc `code/common/checker.py` tutaj to `common/checker.py` tam.

Cztery pliki pipeline'u są w [`../pipeline/`](../pipeline/) zamiast w `.github/` i `.githooks/`, więc GitHub nigdy ich tu nie uruchamia.

Komentarze w tych plikach są po angielsku, zwracają się do czytelnika („you”) i wymieniają moduły laboratorium, np. H6: zbudowałem laboratorium według przewodnika krok po kroku, więc „you” to ja, a H0–H11 to moduły laboratorium ([tabela](../docs/security-design.pl.md#budowa-moduł-po-module)).

## Co pokazuje każdy plik

| Plik | Co pokazuje |
|---|---|
| [functions/function_app.py](functions/function_app.py) | Narzędzia tylko do odczytu jako aplikacja Azure Functions: ścieżki za logowaniem Entra, żadne sprawdzenie nie działa bez soli audytu, żadnych stack trace, nic nie jest zwracane przed zapisaniem rekordu dowodu |
| [functions/shared/validate.py](functions/shared/validate.py) | Allow-listy dla każdego wejścia, limit rozmiaru 2 KB i odmowy, które nigdy nie powtarzają danych wejściowych |
| [functions/shared/audit.py](functions/shared/audit.py) | Jeden wpis audytu na każde uruchomione sprawdzenie, z wywołującym zapisanym jako hash z solą |
| [functions/shared/evidence.py](functions/shared/evidence.py) | Rekordy dowodów: jedna stała postać JSON, hash SHA-256, zapisywane jako tożsamość narzędzi i nigdy nienadpisywane |
| [common/answer.py](common/answer.py) | Ścisły schemat odpowiedzi, wspólny dla agenta i checkera, oraz sprawdzenia, których nie obsługuje ścisły tryb JSON w Azure |
| [common/checker.py](common/checker.py) | Checker: dowód musi istnieć, zgadzać się ze swoim hashem i należeć do tego przebiegu i tej firmy; odpowiedź jest obniżana, nigdy podnoszona; „Tak” wymaga dowodów |
| [common/models.py](common/models.py) | Sprawdzenia planu modeli: żadnych wdrożeń Global, Developer ani Provisioned, przypięte wersje, ostrzeżenia przed wycofaniem modelu |
| [config/models.json](config/models.json) | Plan modeli: typy wdrożeń, wersje, limity szybkości, zadania i daty wycofania |
| [agents/definition.py](agents/definition.py) | Agent typu prompt w Foundry jako kod: jego dwa narzędzia, ścisły JSON, guardrail wskazany przez pełne ID w Azure, reasoning effort |
| [agents/check_agent.py](agents/check_agent.py) | Porównuje działającego agenta z kodem (model, instrukcje, narzędzia, format odpowiedzi, guardrail) i sprawdza, czy guardrail istnieje; opcjonalna próba ze znanym tekstem jailbreaku |
| [eval/gate.yaml](eval/gate.yaml) | Bramka wydania: zasady bezpieczeństwa o zerowej tolerancji i progi jakości |
| [logicapp/pack.schema.json](logicapp/pack.schema.json) | Schemat pakietu przyjmowanego przez Logic App do zatwierdzania |
| [tests/test_workflows.py](tests/test_workflows.py) | 26 testów, które pilnują zasad bezpieczeństwa w workflow CI i wydania |

Jak to się łączy w całość: [docs/security-design.pl.md](../docs/security-design.pl.md).

## Dlaczego nie działa samodzielnie

Te pliki importują części, które zostają prywatne: sprawdzenia dowodów (`functions/shared/checks.py`), czytnik Graph (`functions/shared/sources.py`), katalog i zasady oceny (`common/catalogue.py`, `common/evaluate.py`), wczytywanie ustawień, moduły do obsługi Foundry i skrypt dla wydań (`tools/changed.py`). `tests/test_workflows.py` oczekuje też plików workflow w `.github/` i pliku `requirements.txt` z laboratorium.

Nie zmieniłem żadnego pliku, żeby działał tutaj: każdy jest pokazany dokładnie tak, jak jest w laboratorium. Pełne omówienie kodu jest dostępne na prośbę.
