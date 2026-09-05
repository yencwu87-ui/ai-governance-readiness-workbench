# governance/ — Lane B evidence exports

These are the data contracts Lane B reads. Today they are hand-maintained; later they
become exports from Jira / a registry / your eval harness with the same column names.

| File | Read by | Update when |
|---|---|---|
| tickets.csv | MCM-01, 02, 05, 09 | any change to the assessor, prompts, harness, or Lane B controls |
| model_registry.csv | MCM-02 | a model is added or its tier changes |
| eval_results.json | MCM-03, 04 | every eval run |
| rollback_log.csv | MCM-08 | every rollback test (at least every 180 days) |
| exceptions.csv | MCM-10 | an exception is raised, extended or closed |
| ../deploy.yml | MCM-01, 03 | every deployment |

Ticket ids must appear in commit messages (`WB-002: add review tab`) for MCM-05/06 to join.
The `approver` in tickets.csv must never equal the git author of that ticket's commits.
