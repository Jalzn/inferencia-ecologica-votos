import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { SearchPlace } from '../data/types';
import { placeKindLabel, searchPlaces } from '../results/model';

type Props = {
  places: SearchPlace[];
  onSelect: (id: string) => void;
  available: (id: string) => boolean;
};

export function GeographicSearch({ places, onSelect, available }: Props) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();
  const results = useMemo(() => searchPlaces(places, query), [places, query]);
  useEffect(() => {
    const container = list.current;
    const option = container?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!container || !option) return;
    const viewport = container.getBoundingClientRect();
    const bounds = option.getBoundingClientRect();
    if (bounds.bottom > viewport.bottom) container.scrollTop += bounds.bottom - viewport.bottom + 5;
    else if (bounds.top < viewport.top) container.scrollTop -= viewport.top - bounds.top + 5;
  }, [active, open, query]);
  function select(place: SearchPlace) {
    if (!available(place.id)) return;
    onSelect(place.id);
    setQuery('');
    setOpen(false);
    setActive(0);
  }
  return (
    <div
      className="search"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <span className="search-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <circle cx="10.8" cy="10.8" r="6.5" />
          <path d="m16 16 4.5 4.5" />
        </svg>
      </span>
      <input
        id={`${id}-input`}
        data-testid="geographic-search"
        aria-label="Buscar estado, município ou localidade no exterior"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open && !!query}
        aria-controls={`${id}-list`}
        aria-activedescendant={open && results[active] ? `${id}-${active}` : undefined}
        placeholder="Buscar um lugar"
        autoComplete="off"
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
          setActive(0);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            setOpen(false);
            return;
          }
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            setOpen(true);
            setActive((index) =>
              Math.max(
                0,
                Math.min(results.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)),
              ),
            );
          }
          if (event.key === 'Enter' && open && results[active]) {
            event.preventDefault();
            select(results[active]);
          }
        }}
      />
      {query && (
        <button
          type="button"
          className="search-clear"
          aria-label="Limpar busca"
          onClick={() => {
            setQuery('');
            setOpen(false);
          }}
        >
          ×
        </button>
      )}
      {open && query && (
        <div
          ref={list}
          id={`${id}-list`}
          role="listbox"
          aria-label="Lugares encontrados"
          className="search-results"
        >
          {results.length === 0 && <p className="search-empty">Nenhum lugar encontrado.</p>}
          {results.map((place, index) => (
            <button
              type="button"
              key={place.id}
              id={`${id}-${index}`}
              role="option"
              aria-selected={index === active}
              aria-disabled={!available(place.id)}
              tabIndex={-1}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActive(index)}
              onClick={() => select(place)}
            >
              <span>
                <strong>{place.name}</strong>
                <small>
                  {placeKindLabel(place)}
                  {['state', 'municipality'].includes(place.kind) && place.stateCode !== 'ZZ'
                    ? ` · ${place.stateCode}`
                    : ''}
                </small>
              </span>
              {!available(place.id) ? <em>Base completa</em> : <span aria-hidden="true">↗</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
