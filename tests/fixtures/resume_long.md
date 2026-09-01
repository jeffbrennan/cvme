---
name: Morgan Avery
contact:
  - text: morgan.avery@example.com
    url: mailto:morgan.avery@example.com
  - text: morganavery.example
    url: https://morganavery.example
---

## Summary

Careful handling of operational data changes what a team can decide and how
fast. I have six years of experience across the data lifecycle, and would like
to apply what I have learned on a team that treats pipelines as products.

## Experience

### Staff Data Engineer @ Northwind Analytics | Jul 2023 – Present

- Own the ingestion and transformation of telemetry (8B+ events/week, 120TB+
  lake) for several hundred enterprise tenants
- Designed the streaming backbone that powers near-real-time reporting on
  reliability metrics, drift alerts, and automated recovery from common
  ingestion faults
- Built a CLI that generates orchestration workflows, letting the team tailor
  cluster sizing per tenant without hand-editing job definitions
- Led the migration of 1,200+ legacy pipelines into a source-controlled
  monorepo, adding CI and schema validation with **Pydantic** and **Pytest**
- Wrote a Spark metrics parser that guides which transformations get rewritten

### Data Engineer @ GreyHarbor Health | Dec 2020 – Jul 2023

- Managed calculation and reporting of quality measures across 14 facilities
- Built and maintained the weekly analytics pipeline (90M+ rows, 30k members)
- Led adoption of geospatial analysis by building address cleaning and
  geocoding steps the rest of the team could reuse
- Developed shared data-cleaning helpers in Python and R used by 9 analysts
- Cut dashboard load times from minutes to seconds with composable models

### Data Engineer (contract) @ Cascade Public Health | May 2020 – Sep 2023

- Created and maintained a daily public reporting pipeline drawing on state
  and third-party sources
- Collected data from REST APIs and HTML sources with Python
- Built a monitoring bot and unit tests to keep data quality visible

### Research Coordinator @ Ridgeway Institute | Jan 2019 – Dec 2020

- Authored a thesis on biomarkers of traumatic brain injury and provided
  analysis support across several other studies
- Applied variable selection over hundreds of biomarker combinations
- Built analysis pipelines and publication-ready visualisation in R

### Analytics Engineer @ Beacon Logistics | Mar 2018 – Dec 2018

- Rebuilt the nightly warehouse load, cutting the batch window substantially
- Introduced column-level tests that caught schema drift before it shipped
- Documented every model so on-call could answer questions without escalating
- Migrated reporting off spreadsheets onto a governed semantic layer

### Data Analyst @ Fernwood Retail Group | Jun 2016 – Feb 2018

- Built the weekly demand forecast used by regional planners
- Automated a manual reconciliation that had taken two days each month
- Partnered with finance to define the metrics the board reviewed
- Trained nine analysts on the query patterns the warehouse rewarded

### Reporting Analyst @ Halden Municipal Services | Jan 2015 – May 2016

- Produced the statutory reporting pack against a fixed monthly deadline
- Replaced hand-maintained extracts with scheduled, validated queries
- Wrote the runbook the team still uses for period close
## Education

### Ridgeway University
#### Master of Science - Major in Epidemiology, Minor in Biostatistics | May 2020

Certificate: Data Science

### Lakeshore State University
#### Bachelor of Science - Major in Public Health | May 2018

## Skills

- **Languages**: Python (advanced), SQL (advanced), R (advanced), Scala
  (intermediate), Go (learning)
- **Data Stack**: Transformation (spark, dbt, polars); Orchestration (airflow,
  dagster, step functions); Validation (pytest, pydantic); Distributed
  Computing (spark, docker, kubernetes); Databases (postgres, sql server,
  mongodb); Cloud Platforms (aws, azure, databricks)
- **Certificates**: Professional Data Engineer, Cloud Practitioner
