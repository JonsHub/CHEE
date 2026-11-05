import json
import re
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://hapi.fhir.org/baseR4"
TIMEOUT = 25
KBV_PROFILE = "https://fhir.kbv.de/StructureDefinition/KBV_PR_Base_Patient"


class FhirError(Exception):
    """Raised when the FHIR server cannot complete a request."""


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/fhir+json",
        "User-Agent": "CHEE/0.1",
    }
    if data is not None:
        headers["Content-Type"] = "application/fhir+json"
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            try:
                result = json.loads(resp.read().decode("utf-8"))
            except json.JSONDecodeError as error:
                raise FhirError("The server returned invalid JSON.") from error
            if not isinstance(result, dict) or not result.get("resourceType"):
                raise FhirError("The server returned an invalid FHIR resource.")
            return result
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            response = json.loads(error.read().decode("utf-8"))
            issue = response.get("issue", [{}])[0]
            detail = issue.get("diagnostics") or issue.get("details", {}).get("text", "")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            pass
        message = f"HTTP {error.code} {error.reason}"
        raise FhirError(f"{message} - {detail}" if detail else message) from error
    except urllib.error.URLError as error:
        raise FhirError(f"Server is unreachable: {error.reason}") from error
    except TimeoutError as error:
        raise FhirError("The request timed out.") from error


def _from_bundle(bundle: dict) -> list[dict]:
    if bundle.get("resourceType") != "Bundle":
        raise FhirError("The search response was not a FHIR Bundle.")
    return [
        entry["resource"]
        for entry in bundle.get("entry", [])
        if entry.get("resource", {}).get("resourceType") == "Patient"
    ]


def search_patients(filters: dict[str, str] | None = None) -> tuple[list[dict], str]:
    filters = {key: value.strip() for key, value in (filters or {}).items() if value.strip()}
    if not filters:
        query = "Patient?_count=20&_sort=-_lastUpdated"
        return _from_bundle(_request("GET", query)), "Latest patients"

    params = []
    for key in ("name", "gender", "birthdate", "identifier"):
        if filters.get(key):
            params.append(f"{key}={urllib.parse.quote(filters[key])}")
    query = "Patient?" + "&".join(params) + "&_count=50&_sort=-_lastUpdated"
    return _from_bundle(_request("GET", query)), "Patient filters applied"


def lookup(query: str) -> tuple[list[dict], str]:
    query = query.strip()
    if not query:
        return search_patients()
    if re.fullmatch(r"[A-Za-z0-9\-.]{1,64}", query):
        try:
            patient = _request("GET", f"Patient/{urllib.parse.quote(query)}")
            if patient.get("resourceType") == "Patient":
                return [patient], f"Patient/{query} loaded"
        except FhirError as error:
            if not any(code in str(error) for code in ("404", "410")):
                raise
    return search_patients({"name": query})


def create_patient(
    family: str, given: str, birth_date: str, gender: str
) -> dict:
    patient = {
        "resourceType": "Patient",
        "meta": {"profile": [KBV_PROFILE]},
        "name": [{"use": "official", "family": family, "given": [given]}],
        "birthDate": birth_date,
        "gender": gender,
    }
    return _request("POST", "Patient", patient)


def update_patient(patient_id: str, family: str, given: str, birth_date: str, gender: str) -> dict:
    patient = {
        "resourceType": "Patient",
        "id": patient_id,
        "meta": {"profile": [KBV_PROFILE]},
        "name": [{"use": "official", "family": family, "given": [given]}],
        "birthDate": birth_date,
        "gender": gender,
    }
    return _request("PUT", f"Patient/{urllib.parse.quote(patient_id)}", patient)
