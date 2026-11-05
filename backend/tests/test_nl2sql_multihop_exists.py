"""Batch 2 bounded schema relationship paths using nested EXISTS."""
import sqlite3
import pytest
import sqlglot
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext

def schema(extra=None, *, cycle=False, compound=False):
    tables=[
      {'name':'users','columns':[{'name':'id'}, {'name':'tenant_id'}]},
      {'name':'orders','columns':[{'name':'id'}, {'name':'user_id'}, {'name':'product_id'}, {'name':'tenant_id'}]},
      {'name':'products','columns':[{'name':'id'}] + ([{'name':'user_id'}] if cycle else [])},
      {'name':'payments','columns':[{'name':'id'}, {'name':'order_id'}]},
    ]
    rels=[
      {'from_table':'orders','from_column':'user_id','to_table':'users','to_column':'id'},
      {'from_table':'orders','from_column':'product_id','to_table':'products','to_column':'id'},
      {'from_table':'payments','from_column':'order_id','to_table':'orders','to_column':'id'},
    ]
    if cycle: rels.append({'from_table':'products','from_column':'user_id','to_table':'users','to_column':'id'})
    if compound:
      tables[:2]=[
        {'name':'users','columns':[{'name':'tenant_id'},{'name':'id'}]},
        {'name':'orders','columns':[{'name':'tenant_id'},{'name':'user_id'},{'name':'product_id'},{'name':'id'}]},
      ]
      rels=[{'from_table':'orders','to_table':'users','columns':[{'from_column':'tenant_id','to_column':'tenant_id'},{'from_column':'user_id','to_column':'id'}]}, rels[1]]
    if extra: rels.extend(extra)
    return SchemaContext.from_mapping({'tables':tables,'relationships':rels})

def gen(text, sc): return NL2SQLGenerator().generate(text,'postgres',schema=sc)
def body(r): assert r.success,r.explanation; return ' '.join(l.strip() for l in r.sql.splitlines() if not l.strip().startswith('--'))

def test_two_hop_products_and_payments_nested_exists():
    products=body(gen('users who have products',schema()))
    payments=body(gen('users who have payments',schema()))
    assert 'FROM users WHERE EXISTS' in products and 'FROM orders' in products and 'FROM products' in products
    assert 'FROM users WHERE EXISTS' in payments and 'FROM orders' in payments and 'FROM payments' in payments

def test_direct_relationship_precedes_path():
    direct=schema(extra=[{'from_table':'users','from_column':'id','to_table':'products','to_column':'id'}])
    sql=body(gen('users who have products',direct))
    assert 'FROM products WHERE users.id = products.id' in sql
    assert 'FROM orders' not in sql

def test_not_exists_negates_outer_only():
    sql=body(gen('users without products',schema()))
    assert 'WHERE NOT EXISTS' in sql and 'AND EXISTS' in sql and 'FROM products' in sql

def test_path_and_direct_ambiguity_fail_closed():
    ambiguous=schema(extra=[{'from_table':'orders','from_column':'tenant_id','to_table':'users','to_column':'tenant_id'}])
    assert not gen('users who have orders',ambiguous).success
    two_paths=schema(extra=[
        {'from_table':'users','from_column':'id','to_table':'products','to_column':'id'},
    ])
    assert gen('users who have products',two_paths).success

    alternate_map = {
        'tables': [
            {'name': table.name, 'columns': [{'name': column} for column in table.columns]}
            for table in schema().tables
        ] + [{'name':'catalog','columns':[{'name':'id'}]}],
        'relationships': [
            {'from_table': relationship.from_table, 'from_column': relationship.column_pairs[0][0],
             'to_table': relationship.to_table, 'to_column': relationship.column_pairs[0][1]}
            for relationship in schema().relationships
        ] + [
            {'from_table':'users','from_column':'id','to_table':'catalog','to_column':'id'},
            {'from_table':'catalog','from_column':'id','to_table':'products','to_column':'id'},
        ],
    }
    alternate = SchemaContext.from_mapping(alternate_map)
    assert not gen('users who have products', alternate).success

def test_cycle_unique_simple_path_and_three_hop_fail():
    assert gen('users who have products',schema(cycle=True)).success
    three=schema(); three_tables=list(three.tables)
    three_tables.append(type(three.tables[0])('shipments',frozenset({'id','payment_id'}),True))
    three_map={'tables':[{'name':t.name,'columns':[{'name':c} for c in t.columns]} for t in three_tables], 'relationships':[{'from_table':r.from_table,'from_column':r.from_column,'to_table':r.to_table,'to_column':r.to_column} for r in three.relationships]}
    three_map['relationships'].append({'from_table':'shipments','from_column':'payment_id','to_table':'payments','to_column':'id'})
    assert not gen('users who have shipments',SchemaContext.from_mapping(three_map)).success

def test_path_filters_aggregation_and_physical_join_fail_closed():
    for text in ['users who have products where id = 1','count products per user','users joined with products']:
        assert not gen(text,schema()).success

def test_composite_path_uses_all_pairs():
    sql=body(gen('users who have products',schema(compound=True)))
    assert 'users.tenant_id = orders.tenant_id' in sql and 'users.id = orders.user_id' in sql

def test_no_schema_unchanged():
    result=NL2SQLGenerator().generate('users who have products','postgres')
    assert result.success and 'WHERE EXISTS' in result.sql

def test_sqlite_runtime_semantics():
    conn=sqlite3.connect(':memory:'); conn.executescript('CREATE TABLE users(id); CREATE TABLE orders(id,user_id,product_id); CREATE TABLE products(id); INSERT INTO users VALUES(1),(2),(3); INSERT INTO orders VALUES(1,1,10),(2,1,10),(3,2,20); INSERT INTO products VALUES(10),(20);')
    sql='SELECT users.id FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE orders.user_id = users.id AND EXISTS (SELECT 1 FROM products WHERE orders.product_id = products.id))'
    assert list(conn.execute(sql)) == [(1,),(2,)]

@pytest.mark.parametrize('dialect',['mysql','postgres','oracle','tsql','hive','spark','trino','databricks','snowflake','redshift','clickhouse','duckdb'])
def test_nested_exists_parseable(dialect):
    result=gen('users who have products',schema()); assert result.success; assert sqlglot.parse_one(result.sql,read=dialect) is not None

def test_deterministic():
    assert gen('users who have products',schema()).sql == gen('users who have products',schema()).sql
