"""roles — role definitions as structured contracts.

Every role is defined by three identity fields (architype, sub-architype,
personality) plus the standard structured contract (mandate, input spec,
output schema) and the shared output envelope.

`roles/base.py` also spins a deterministic `sub_architype` + `personality`
(`spin_personality` / `spin_sub_architype`) for dynamically-created roles
(managers/ICs in Phase 4), so a spun role is never left with an empty
identity.
"""
