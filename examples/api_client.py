#!/usr/bin/env python3
"""API client examples for SQL Dialect Master.

Make sure the API server is running:
    uvicorn backend.api.main:app --reload
"""
import requests

BASE_URL = "http://localhost:8000"


def convert_sql():
    """Convert SQL between dialects."""
    print("1. SQL Conversion")
    print("-" * 40)
    
    response = requests.post(f"{BASE_URL}/api/convert", json={
        "sql": "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders LIMIT 10",
        "source_dialect": "mysql",
        "target_dialect": "postgres"
    })
    result = response.json()
    
    print(f"Success: {result['success']}")
    print(f"Target SQL:\n{result.get('target_sql')}")
    if result.get('transformations'):
        print(f"Transformations: {result['transformations']}")
    print()


def nl2sql():
    """Generate SQL from natural language."""
    print("2. NL2SQL")
    print("-" * 40)
    
    response = requests.post(f"{BASE_URL}/api/nl2sql", json={
        "text": "统计每个部门的员工数量",
        "dialect": "mysql"
    })
    result = response.json()
    
    print(f"Input: {result['input_text']}")
    print(f"SQL: {result.get('sql')}")
    print(f"Confidence: {result.get('confidence')}")
    print()


def search_functions():
    """Search SQL functions."""
    print("3. Function Search")
    print("-" * 40)
    
    response = requests.get(f"{BASE_URL}/api/functions", params={
        "search": "DATE",
        "limit": 5
    })
    result = response.json()
    
    print(f"Found {result['count']} functions:")
    for func in result['functions'][:3]:
        print(f"  - {func['name']}: {func.get('description', '')}")
    print()


def map_type():
    """Map data types between dialects."""
    print("4. Type Mapping")
    print("-" * 40)
    
    response = requests.post(f"{BASE_URL}/api/types/map", json={
        "type_name": "VARCHAR",
        "source_dialect": "mysql",
        "target_dialect": "oracle"
    })
    result = response.json()
    
    print(f"VARCHAR: {result['source_dialect']} → {result['target_dialect']}")
    print(f"  Source: {result['source_type']}")
    print(f"  Target: {result['target_type']}")
    print()


def health_check():
    """Check API health."""
    print("5. Health Check")
    print("-" * 40)
    
    response = requests.get(f"{BASE_URL}/health")
    result = response.json()
    
    print(f"Status: {result['status']}")
    print(f"Version: {result['version']}")
    print()


if __name__ == "__main__":
    print("=" * 50)
    print("SQL Dialect Master - API Examples")
    print("=" * 50)
    print()
    
    try:
        health_check()
        convert_sql()
        nl2sql()
        search_functions()
        map_type()
    except requests.exceptions.ConnectionError:
        print("Error: Cannot connect to API server.")
        print("Please start the server first:")
        print("  uvicorn backend.api.main:app --reload")
