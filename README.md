# CHEE

**Comprehensive FHIR Engine** is a small Tkinter desktop client for the HAPI
FHIR R4 test server. It focuses on the German KBV patient profile and provides
a readable patient view instead of exposing only raw JSON.

FHIR endpoint: `https://hapi.fhir.org/baseR4`

## Features

The action menu provides four workflows:

* **Fetch** loads a patient by ID or searches by name. Empty input shows the
  latest patients.
* **Create** creates a Patient resource from family name, given name, birth
  date, and gender. The new resource, its server-generated ID, and the
  `KBV_PR_Base_Patient` profile are displayed after a successful request.
* **Update** pre-fills the form from the selected patient and updates that
  resource on the server. A success or error message is shown in the status
  bar.
* **Filter** searches by name, gender, birth date/year, and identifier. The
  result list shows a short name/ID summary and the number of matches.

All network requests run in a background thread, so the interface stays
responsive. HTTP, timeout, invalid-response, and server-connection failures
are reported to the user.

## Requirements

* Python 3.10 or newer
* Tkinter
* Internet access to the HAPI FHIR test server

The application uses only Python standard-library modules.

## Run

```bash
python3 main.py
```

The equivalent direct entry point is:

```bash
python3 chee.py
```

## Test

Run the unit tests from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

The tests mock HTTP calls and verify profile-aware creation, ID-specific
updates, and construction of all supported search filters. They do not modify
the public test server.

## Project structure

* `main.py` is the small application entry point.
* `chee.py` contains the Tkinter window, patient presentation, and user
  feedback.
* `fhir_client.py` contains FHIR HTTP operations and resource construction.
* `tests/` contains isolated unit tests for the FHIR client.

The test server is shared and may remove or change resources. Do not use it
with real patient data.
