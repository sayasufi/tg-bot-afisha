"""Чистые алгоритмы матчинга (дедуп): сравнение названий/площадок, решение о слиянии.
Foundation-уровень (без БД/IO) — поэтому в core, а не в pipeline; импортится и core.db.repositories, и pipeline, и worker."""
