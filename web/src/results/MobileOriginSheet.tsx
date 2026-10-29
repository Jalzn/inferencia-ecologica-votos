import { useEffect, useId, useRef, useState } from 'react';
import type { DisplayGroup, Manifest, Place } from '../data/types';
import { smallBaseShort } from './copy';
import { formatPercent, isSmallBase, share, summarize } from './model';
import { OriginPanel } from './OriginPanel';

type Props = {
  manifest: Manifest;
  place: Place;
  selectedGroup: DisplayGroup;
  onSelect: (id: string) => void;
  onDetails: () => void;
};

export function MobileOriginSheet(props: Props) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useId();
  const row = summarize(props.place, props.selectedGroup);
  const lula = formatPercent(share(row.estimated.lula, row.observed));
  const flavio = formatPercent(share(row.estimated.flavio, row.observed));
  const smallBase = isSmallBase(row.observed);

  useEffect(() => {
    const element = dialog.current;
    if (open) element?.showModal();
    else element?.close();
    return () => {
      if (element?.open) element.close();
    };
  }, [open]);

  return (
    <>
      <button
        id="results"
        type="button"
        className="mobile-origin-launcher"
        data-testid="mobile-origin-launcher"
        aria-label={`Escolher origem. ${props.selectedGroup.label}: Lula ${lula}, Flávio ${flavio}. Percentuais estimados sobre o total desta origem no primeiro turno.${smallBase ? ` ${smallBaseShort}.` : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(true)}
      >
        <span className="launcher-origin">
          <small>ORIGEM NO 1º TURNO</small>
          <strong>{props.selectedGroup.label}</strong>
          <span>Ver todas as origens</span>
        </span>
        <span className="launcher-share">
          <small>
            <i className="dot red" />
            Lula
          </small>
          <strong>{lula}</strong>
        </span>
        <span className="launcher-share">
          <small>
            <i className="dot blue" />
            Flávio
          </small>
          <strong>{flavio}</strong>
        </span>
        <span className="launcher-chevron" aria-hidden="true">
          ⌃
        </span>
        <span className="launcher-denominator">% do total desta origem</span>
        {smallBase && (
          <span className="launcher-small-base" data-testid="launcher-small-base">
            <span className="small-base-swatch" aria-hidden="true" />
            {smallBaseShort}
          </span>
        )}
      </button>
      <dialog
        id={id}
        ref={dialog}
        className="origin-sheet"
        data-testid="origin-sheet"
        aria-label="Escolher origem no primeiro turno"
        onClose={() => setOpen(false)}
        onClick={(event) => {
          if (event.target === dialog.current) setOpen(false);
        }}
      >
        <div className="sheet-toolbar">
          <span>Origens · {props.place.name}</span>
          <button
            type="button"
            className="icon-button"
            aria-label="Fechar origens"
            onClick={() => setOpen(false)}
          >
            ×
          </button>
        </div>
        <div className="sheet-body">
          <OriginPanel
            {...props}
            onSelect={(origin) => {
              props.onSelect(origin);
              setOpen(false);
            }}
            onDetails={() => {
              setOpen(false);
              props.onDetails();
            }}
          />
        </div>
      </dialog>
    </>
  );
}
