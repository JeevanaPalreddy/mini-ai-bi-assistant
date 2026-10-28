AI Development Notes

1. AI Tools Used

* Claude (Anthropic API): Used as the natural-language interpreter in the Mini AI Business Intelligence Assistant.
* AI coding assistance: Used to help with implementation guidance, code review, debugging suggestions, and documentation where applicable.

2. How AI Was Used

Claude interprets a user’s natural-language business question and produces a structured query specification (QuerySpec). The application validates this specification and converts it into a safe SQL query.

The model does not generate SQL directly. The application uses predefined column and query constraints, along with parameterized values, to reduce the risk of unsafe queries.

When an API key is unavailable or the AI request fails, the application uses a rule-based fallback for supported questions.

3. Challenges and Debugging

* Natural-language interpretation: Different ways of asking the same business question can be difficult to interpret consistently. A structured query specification helps standardize the output.
* Data accuracy: Revenue calculations and grouped results need to match the defined business rules. Automated tests and an independent Pandas cross-check were used to verify calculations.
* Reliability: The application includes a rule-based fallback for situations where the AI service is unavailable or cannot interpret a request.

4. Testing and Validation

The automated test suite was executed using python -m pytest -q. The test suite passed all 21 tests during validation.

The independent cross-check was executed using python crosscheck.py. All reported calculation differences were 0.00.

5. Improvements With One More Day

* Add support for more natural-language question variations.
* Improve error messages for unsupported or ambiguous questions.
* Add more tests for invalid inputs and AI API failures.
* Improve charts and business insights in the Streamlit interface.
* Add clearer logging and monitoring for AI requests and fallback usage.

6. Limitations

* The rule-based fallback supports only a limited range of question patterns.
* Queries are restricted to supported metrics, groupings, and filters.
* The application currently works with one sales CSV dataset.
* AI-powered interpretation requires a valid Anthropic API key and network access.
