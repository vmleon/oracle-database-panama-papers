-- Recreate Property Graph with correct edge definitions
-- Run from SQLcl: sql -name panama @database/scripts/recreate-graph.sql

DROP PROPERTY GRAPH panama_papers.panama_graph;

CREATE PROPERTY GRAPH panama_papers.panama_graph
    VERTEX TABLES (
        panama_papers.entities
            KEY (node_id)
            PROPERTIES (node_id, name, jurisdiction, jurisdiction_desc, country_codes, countries,
                       incorporation_date, inactivation_date, status, source_id),
        panama_papers.officers
            KEY (node_id)
            PROPERTIES (node_id, name, country_codes, countries, source_id),
        panama_papers.intermediaries
            KEY (node_id)
            PROPERTIES (node_id, name, country_codes, countries, status, source_id),
        panama_papers.addresses
            KEY (node_id)
            PROPERTIES (node_id, address, country_codes, countries, source_id)
    )
    EDGE TABLES (
        panama_papers.relationships AS officer_edges
            KEY (rel_id)
            SOURCE KEY (node_id_start) REFERENCES officers (node_id)
            DESTINATION KEY (node_id_end) REFERENCES entities (node_id)
            PROPERTIES (rel_type, source_id),
        panama_papers.relationships AS intermediary_edges
            KEY (rel_id)
            SOURCE KEY (node_id_start) REFERENCES intermediaries (node_id)
            DESTINATION KEY (node_id_end) REFERENCES entities (node_id)
            PROPERTIES (rel_type, source_id),
        panama_papers.relationships AS address_edges
            KEY (rel_id)
            SOURCE KEY (node_id_start) REFERENCES addresses (node_id)
            DESTINATION KEY (node_id_end) REFERENCES entities (node_id)
            PROPERTIES (rel_type, source_id),
        panama_papers.relationships AS entity_edges
            KEY (rel_id)
            SOURCE KEY (node_id_start) REFERENCES entities (node_id)
            DESTINATION KEY (node_id_end) REFERENCES entities (node_id)
            PROPERTIES (rel_type, source_id)
    );

SELECT 'Graph created successfully' AS status FROM dual;
