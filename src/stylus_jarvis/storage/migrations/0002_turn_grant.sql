-- Earlier turns have no recorded admission revision. Leave their history intact.
ALTER TABLE turns ADD COLUMN grant_revision INTEGER;
