import { useEffect, useRef, useState } from 'react';
import { loadCatalogs, persistCatalogs } from './catalog-storage.js';

export function useStoredCatalogs(kind) {
  const [loaded] = useState(() => loadCatalogs(kind));
  const [catalogs, setCatalogs] = useState(loaded.catalogs);
  const [errors, setErrors] = useState(loaded.errors);
  const previous = useRef(loaded.catalogs);
  useEffect(() => {
    const result = persistCatalogs(kind, catalogs, previous.current);
    previous.current = result.saved;
    setErrors([...loaded.errors, ...result.errors]);
  }, [kind, catalogs, loaded]);
  return [catalogs, setCatalogs, errors];
}
