import { useEffect, useRef, useState } from 'react';
import { loadDocuments, persistDocuments } from './document-storage.js';

export function useStoredDocuments(kind) {
  const [loaded] = useState(() => loadDocuments(kind));
  const [documents, setDocuments] = useState(loaded.documents);
  const [errors, setErrors] = useState(loaded.errors);
  const previous = useRef(loaded.documents);
  useEffect(() => {
    const result = persistDocuments(kind, documents, previous.current);
    previous.current = result.saved;
    setErrors([...loaded.errors, ...result.errors]);
  }, [kind, documents, loaded]);
  return [documents, setDocuments, errors];
}
