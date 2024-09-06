import json
import os
import sys

import prance
import requests
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI


def analyze_spec(spec):
    global_consumes = spec.get('consumes', ['application/json'])
    operations = []
    for path, path_item in spec['paths'].items():
        for method, operation in path_item.items():
            if method in ['get', 'post', 'put', 'delete', 'patch']:
                # Use operation-level 'consumes' if available, otherwise use global 'consumes'
                consumes = operation.get('consumes', global_consumes)
                operations.append({
                    'path': path,
                    'method': method,
                    'operation_id': operation.get('operationId', f"{method}_{path}"),
                    'parameters': operation.get('parameters', []),
                    'requestBody': operation.get('requestBody', {}),
                    'responses': operation.get('responses', {}),
                    'consumes': consumes
                })
    return operations


def generate_test_case(operation):
    operation_string = json.dumps(operation)

    prompt_text = f"""
    Here is the API operation data: {operation_string}
    Please generate API test cases for this operation in JSON format.
    No extra description before or after the json object should be added to the output.
    The JSON should include the following fields:
    - test_name: A descriptive name for the test case
    - request: An object containing 'method', 'path', 'headers', and 'body' (if applicable)
    - expected_response: An object containing 'status_code' and 'body' (sample expected response)
    Ensure that the 'headers' in the request include the appropriate Content-Type based on the 'consumes' field of the operation.
    """

    model = ChatOpenAI(model="gpt-4o-mini")
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an API testing expert. Generate test cases in JSON format."),
        MessagesPlaceholder("msgs")
    ])

    output_parser = JsonOutputParser()
    chain = prompt | model | output_parser

    test_case = chain.invoke({"msgs": [HumanMessage(content=prompt_text)]})
    return test_case


def run_test_case(base_url, test_case, operation):
    request = test_case['request']
    url = f"{base_url}{request['path']}"
    method = request['method'].lower()
    headers = request.get('headers', {})
    body = request.get('body')

    # Ensure the correct Content-Type is set based on the operation's 'consumes'
    if 'Content-Type' not in headers and operation['consumes']:
        headers['Content-Type'] = operation['consumes'][0]

    try:
        if headers.get('Content-Type') == 'application/x-www-form-urlencoded':
            response = requests.request(method, url, headers=headers, data=body)
        else:
            response = requests.request(method, url, headers=headers, json=body)

        actual_status = response.status_code
        actual_body = response.json() if response.text else None

        expected_status = test_case['expected_response']['status_code']
        expected_body = test_case['expected_response'].get('body')

        result = {
            'test_name': test_case['test_name'],
            'passed': actual_status == expected_status,
            'expected_status': expected_status,
            'actual_status': actual_status,
            'expected_body': expected_body,
            'actual_body': actual_body
        }

        return result

    except Exception as e:
        return {
            'test_name': test_case['test_name'],
            'passed': False,
            'error': str(e)
        }


def main():
    openapi_spec_file = sys.argv[1]
    base_url = sys.argv[2]
    openapi_spec = prance.ResolvingParser(openapi_spec_file).specification
    operations = analyze_spec(openapi_spec)

    all_test_cases = []
    for operation in operations:
        print(f"Generating test case for: {operation['method']} {operation['path']}")
        test_case = generate_test_case(operation)
        all_test_cases.extend(test_case)

    # Save all test cases to a JSON file
    with open('test_cases.json', 'w') as f:
        json.dump(all_test_cases, f, indent=4)

    print("Test cases saved to test_cases.json")

    # Run the test cases
    test_results = []
    for test_case, operation in zip(all_test_cases, operations):
        result = run_test_case(base_url, test_case, operation)
        test_results.append(result)
        if not result['passed']:
            print(f"Test failed: {result['test_name']}")
            print(f"Expected status: {result.get('expected_status')}")
            print(f"Actual status: {result.get('actual_status')}")
            if 'error' in result:
                print(f"Error: {result['error']}")
        print("---")

    # Save test results
    with open('test_results.json', 'w') as f:
        json.dump(test_results, f, indent=4)

    print("Test results saved to test_results.json")


if __name__ == "__main__":
    main()
