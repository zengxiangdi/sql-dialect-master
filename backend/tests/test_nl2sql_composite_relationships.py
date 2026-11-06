"""Composite relationship normalization and direct SQL contracts."""
import sqlite3
import pytest
import sqlglot
from fastapi.testclient import TestClient
from backend.api import main
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext, SchemaValidationError


def composite_schema():
    return {
        'tables':[{'name':'users','columns':[{'name':'tenant_id'},{'name':'id'}]}, {'name':'orders','columns':[{'name':'tenant_id'},{'name':'user_id'},{'name':'id'}]}],
        'relationships':[{'from_table':'orders','to_table':'users','columns':[{'from_column':'tenant_id','to_column':'tenant_id'},{'from_column':'user_id','to_column':'id'}]}]
    }

def generate(text, schema): return NL2SQLGenerator().generate(text,'postgres',schema=SchemaContext.from_mapping(schema))

def body(result):
    assert result.success, result.explanation
    return ' '.join(l.strip() for l in result.sql.splitlines() if not l.strip().startswith('--'))

def test_legacy_relationship_is_unchanged():
    schema={'tables':[{'name':'users','columns':[{'name':'id'}]},{'name':'orders','columns':[{'name':'user_id'}]}],'relationships':[{'from_table':'orders','from_column':'user_id','to_table':'users','to_column':'id'}]}
    assert 'ON users.id = orders.user_id' in body(generate('users join orders',schema))

def test_composite_direct_join_and_reverse_exists_condition():
    sql=body(generate('users join orders',composite_schema()))
    assert 'ON users.tenant_id = orders.tenant_id AND users.id = orders.user_id' in sql
    context=SchemaContext.from_mapping(composite_schema())
    reverse=context.relationship_candidates('users','orders')[0]
    assert reverse.column_pairs == (('tenant_id','tenant_id'),('id','user_id'))
    assert all(x in body(generate('users who have orders',composite_schema())) for x in ['users.id = orders.user_id','users.tenant_id = orders.tenant_id'])

def test_composite_joined_with_and_group_label_fail_closed():
    assert 'ON orders.tenant_id = users.tenant_id AND orders.user_id = users.id' in body(generate('users joined with orders',composite_schema()))
    result=generate('count orders per user',composite_schema()); assert result.success is False
    result=generate('users joined on orders.user_id = users.id',composite_schema()); assert result.success is False

def test_parallel_relationships_remain_ambiguous():
    s=composite_schema(); s['relationships'].append({'from_table':'orders','from_column':'id','to_table':'users','to_column':'id'})
    assert generate('users joined with orders',s).success is False

def test_mixed_invalid_composite_core_inputs_are_invalid():
    s=composite_schema(); s['relationships'][0]['from_column']='user_id'; s['relationships'][0]['to_column']='id'
    s['relationships'][0]['columns']=[{'from_column':'tenant_id','to_column':'tenant_id'}]
    assert not SchemaContext.from_mapping(s).is_valid
    for bad in [
        {'from_table':'orders','to_table':'users','columns':[]},
        {'from_table':'orders','to_table':'users','columns':[{'from_column':'x','to_column':'x'}]*9},
        {'from_table':'orders','to_table':'users','columns':[{'from_column':'tenant_id','to_column':'tenant_id'},{'from_column':'tenant_id','to_column':'tenant_id'}]},
    ]:
        assert not SchemaContext.from_mapping({'tables':composite_schema()['tables'],'relationships':[bad]}).is_valid

def test_composite_tenant_isolation_sqlite():
    conn=sqlite3.connect(':memory:'); conn.executescript('CREATE TABLE users(tenant_id,id); CREATE TABLE orders(tenant_id,user_id); INSERT INTO users VALUES(1,1),(2,1); INSERT INTO orders VALUES(1,1);')
    sql='SELECT users.tenant_id, users.id FROM users JOIN orders ON orders.tenant_id = users.tenant_id AND orders.user_id = users.id'
    assert list(conn.execute(sql)) == [(1,1)]

def test_no_schema_unchanged():
    r=NL2SQLGenerator().generate('users joined with orders','postgres'); assert r.success and 'WHERE EXISTS' in r.sql

@pytest.mark.parametrize('dialect',['mysql','postgres','oracle','tsql','hive','spark','trino','databricks','snowflake','redshift','clickhouse','duckdb'])
def test_composite_sql_parses(dialect):
    r=NL2SQLGenerator().generate('users join orders',dialect,schema=SchemaContext.from_mapping(composite_schema()));
    assert r.success
    assert sqlglot.parse_one(r.sql, read=dialect) is not None

def test_repeated_deterministic():
    a=body(generate('users join orders',composite_schema())); b=body(generate('users join orders',composite_schema())); assert a==b
