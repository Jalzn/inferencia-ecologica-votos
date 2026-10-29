import type { DisplayGroup, Manifest, Place } from '../data/types';
import { smallBaseNote } from './copy';
import {
  formatCompact,
  formatCount,
  formatPercent,
  hasAssociatedSections,
  initials,
  isSmallBase,
  share,
  summarize,
} from './model';

type Props = {
  manifest: Manifest;
  place: Place;
  selectedGroup: DisplayGroup;
  onSelect: (id: string) => void;
  onDetails: () => void;
};

export function OriginPanel({ manifest, place, selectedGroup, onSelect, onDetails }: Props) {
  const chosen = summarize(place, selectedGroup);
  const hasSections = hasAssociatedSections(place);
  return (
    <aside className="results-panel" aria-label="Destinos estimados por origem">
      <div className="results-title">
        <h2>
          Origens dos votos <span className="results-place">· {place.name}</span>
        </h2>
        <p>Selecione uma origem para ver o mapa.</p>
      </div>
      {!hasSections && (
        <p className="no-sections-notice" data-testid="no-sections-notice" role="status">
          Sem seções de votação associadas a esta área. Não há base eleitoral para estimar as
          parcelas.
        </p>
      )}
      <div className="results-columns" aria-hidden="true">
        <span>Origem no 1º turno</span>
        <span>
          <i className="dot red" />
          Lula
        </span>
        <span>
          <i className="dot blue" />
          Flávio
        </span>
      </div>
      <div className="origin-list">
        {manifest.displayGroups.map((group) => {
          const row = summarize(place, group);
          const lula = share(row.estimated.lula, row.observed),
            flavio = share(row.estimated.flavio, row.observed);
          const other = share(
            row.estimated.blank + row.estimated.null + row.estimated.abstention,
            row.observed,
          );
          const active = selectedGroup.id === group.id;
          const symbol =
            group.id === 'blank'
              ? '○'
              : group.id === 'null'
                ? '×'
                : group.id === 'abstention'
                  ? '–'
                  : initials(group.label);
          return (
            <button
              key={group.id}
              type="button"
              data-testid={`origin-${group.id}`}
              className={`origin-row ${active ? 'is-active' : ''} ${row.observed === 0 ? 'is-empty' : ''}`}
              aria-pressed={active}
              aria-label={`${group.label}: Lula ${formatPercent(lula)}, Flávio ${formatPercent(flavio)}. ${!hasSections ? 'Sem seções de votação associadas.' : row.observed ? `${formatCount(row.observed)} na origem.${isSmallBase(row.observed) ? ' Base pequena.' : ''}` : 'Sem votos desta origem.'}`}
              onClick={() => onSelect(group.id)}
            >
              <span className="origin-avatar" aria-hidden="true">
                {symbol}
              </span>
              <span className="origin-name">{group.label}</span>
              <strong className="origin-share lula-share">{formatPercent(lula)}</strong>
              <strong className="origin-share flavio-share">{formatPercent(flavio)}</strong>
              <span className="transfer-bar" aria-hidden="true">
                {row.observed > 0 ? (
                  <>
                    <span className="transfer-lula" style={{ width: `${lula! * 100}%` }} />
                    <span className="transfer-other" style={{ width: `${other! * 100}%` }} />
                    <span className="transfer-flavio" style={{ width: `${flavio! * 100}%` }} />
                  </>
                ) : (
                  <span className="transfer-absent" />
                )}
              </span>
              {active && (
                <span className="origin-counts">
                  <span>
                    {!hasSections
                      ? 'Sem seções associadas'
                      : row.observed
                        ? `${formatCompact(row.estimated.lula)} para Lula`
                        : 'Origem ausente nesta seleção'}
                  </span>
                  <span>
                    {row.observed ? `${formatCompact(row.estimated.flavio)} para Flávio` : ''}
                  </span>
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div className="selected-summary">
        <span>
          {hasSections ? (
            <>
              <strong>{formatCount(chosen.observed)}</strong> na origem selecionada
            </>
          ) : (
            <strong>Sem base eleitoral associada</strong>
          )}
        </span>
        {isSmallBase(chosen.observed) && (
          <p className="small-base-note" data-testid="small-base-note">
            <span className="small-base-swatch" aria-hidden="true" />
            {smallBaseNote}
          </p>
        )}
        <button type="button" data-testid="open-details" onClick={onDetails}>
          Ver quantidades e faixas <span aria-hidden="true">↗</span>
        </button>
      </div>
      <p className="results-note">
        <span className="neutral-key" aria-hidden="true" />
        Nas barras, cinza: branco, nulo ou abstenção no 2º turno.
        <br />
        Estimativas sobre o total de cada origem.
      </p>
    </aside>
  );
}
