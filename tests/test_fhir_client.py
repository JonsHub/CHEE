import unittest
from unittest.mock import patch

import fhir_client


class FhirClientTests(unittest.TestCase):
    @patch("fhir_client._request")
    def test_create_patient_contains_kbv_profile(self, request):
        request.return_value = {"resourceType": "Patient", "id": "123"}

        result = fhir_client.create_patient("Mustermann", "Erika", "1985-10-25", "female")

        request.assert_called_once_with("POST", "Patient", {
            "resourceType": "Patient",
            "meta": {"profile": [fhir_client.KBV_PROFILE]},
            "name": [{"use": "official", "family": "Mustermann", "given": ["Erika"]}],
            "birthDate": "1985-10-25",
            "gender": "female",
        })
        self.assertEqual(result["id"], "123")

    @patch("fhir_client._request")
    def test_update_patient_uses_patient_id(self, request):
        request.return_value = {"resourceType": "Patient", "id": "123"}

        fhir_client.update_patient("123", "New", "Name", "2000-01-01", "unknown")

        self.assertEqual(request.call_args.args[0:2], ("PUT", "Patient/123"))

    @patch("fhir_client._request")
    def test_search_builds_all_supported_filters(self, request):
        request.return_value = {"resourceType": "Bundle", "entry": []}

        patients, message = fhir_client.search_patients({
            "name": "Erika Mustermann",
            "gender": "female",
            "birthdate": "1985",
            "identifier": "123",
        })

        path = request.call_args.args[1]
        self.assertIn("name=Erika%20Mustermann", path)
        self.assertIn("gender=female", path)
        self.assertIn("birthdate=1985", path)
        self.assertIn("identifier=123", path)
        self.assertEqual(patients, [])
        self.assertEqual(message, "Patient filters applied")


if __name__ == "__main__":
    unittest.main()
