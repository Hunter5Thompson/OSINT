// Run only after the duplicate preflight passes and SHOW INDEXES confirms that
// entity_name_type is a standalone RANGE index on Entity(name,type), with no
// owningConstraint. Keep writers paused until the uniqueness constraint is ONLINE.
DROP INDEX entity_name_type IF EXISTS;
