import { useEffect, useRef } from 'react';
import type { DisplayGroup, FinalistRanges, Manifest, Place } from '../data/types';
import { smallBaseNote } from '../results/copy';
import {
  formatCount,
  formatPercent,
  hasAssociatedSections,
  isSmallBase,
  share,
  smallBaseLimit,
  type SummaryRow,
} from '../results/model';

type Props = {
  open: boolean;
  onClose: () => void;
  manifest: Manifest;
  place: Place;
  group: DisplayGroup;
  row: SummaryRow;
  mode: 'method' | 'detail';
};

function RangeGrid({
  ranges,
  observed,
  testId,
}: {
  ranges: FinalistRanges;
  observed: number;
  testId: string;
}) {
  return (
    <div className="range-grid" data-testid={testId}>
      {(['lula', 'flavio'] as const).map((id) => (
        <div key={id}>
          <span>{id === 'lula' ? 'Lula' : 'Flávio'}</span>
          <strong>
            {formatPercent(share(ranges[id].min, observed))} –{' '}
            {formatPercent(share(ranges[id].max, observed))}
          </strong>
        </div>
      ))}
    </div>
  );
}

export function MethodDialog({ open, onClose, manifest, place, group, row, mode }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const hasSections = hasAssociatedSections(place);
  const grouped = group.members.length > 1;
  useEffect(() => {
    if (open) dialog.current?.showModal();
    else dialog.current?.close();
  }, [open]);
  const destinations = [
    ['lula', 'Lula'],
    ['flavio', 'Flávio Bolsonaro'],
    ['blank', 'Branco'],
    ['null', 'Nulo'],
    ['abstention', 'Abstenção'],
  ] as const;
  return (
    <dialog
      ref={dialog}
      className="method-dialog"
      aria-labelledby="method-title"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      <div className="dialog-header">
        <span className="eyebrow">ELEIÇÕES · MÉTODO</span>
        <button
          type="button"
          className="icon-button"
          aria-label="Fechar explicação"
          onClick={onClose}
        >
          ×
        </button>
      </div>
      <h2 id="method-title">
        {mode === 'detail' ? 'Por trás desta estimativa' : 'O que o mapa nos conta'}
      </h2>
      <p className="dialog-intro">
        O voto é secreto. Os dados por seção mostram totais, mas não revelam como cada pessoa votou
        nos dois turnos.
      </p>
      {mode === 'detail' && (
        <section className="detail-section">
          <div className="detail-heading">
            <div>
              <span className="eyebrow">{place.name}</span>
              <h3>{group.label}</h3>
            </div>
            <strong>
              {hasSections ? formatCount(row.observed) : '—'}
              <small>{hasSections ? 'na origem' : 'sem base associada'}</small>
            </strong>
          </div>
          {isSmallBase(row.observed) && (
            <p className="small-base-note" data-testid="detail-small-base-note">
              <span className="small-base-swatch" aria-hidden="true" />
              {smallBaseNote}
            </p>
          )}
          <table>
            <caption className="sr-only">Destinos estimados da origem {group.label}</caption>
            <thead>
              <tr>
                <th>Destino</th>
                <th>Parcela</th>
                <th>Quantidade estimada</th>
              </tr>
            </thead>
            <tbody>
              {destinations.map(([id, label]) => (
                <tr key={id}>
                  <td>{label}</td>
                  <td>{formatPercent(share(row.estimated[id], row.observed))}</td>
                  <td>{hasSections ? formatCount(row.estimated[id], true) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            {hasSections
              ? 'O denominador é toda a origem no primeiro turno, incluindo quem termina em branco, nulo ou abstenção.'
              : 'Esta área não tem seções de votação associadas. Não é possível inferir o apoio dos moradores a partir dessa ausência de dados.'}
          </p>
          <h3>Variação entre especificações</h3>
          <p data-testid="sensitivity-description">{manifest.model.sensitivityDescription}</p>
          {grouped ? (
            <p data-testid="sensitivity-unavailable">
              A origem reúne nulos na urna e nulos técnicos. Uma faixa conjunta não foi calculada;
              somar os extremos separados não produziria uma faixa válida.
            </p>
          ) : row.sensitivity && row.observed > 0 ? (
            <RangeGrid
              ranges={row.sensitivity}
              observed={row.observed}
              testId="sensitivity-range"
            />
          ) : (
            <p data-testid="sensitivity-unavailable">
              Não há faixa disponível para esta origem e seleção.
            </p>
          )}
          {!grouped && row.sensitivity && row.observed > 0 && (
            <p className="callout">
              Estas faixas descrevem {manifest.model.scenarioCount} especificações do modelo.{' '}
              <strong>Não são intervalos de confiança.</strong>
            </p>
          )}
          <h3>Limites de identificação</h3>
          <p data-testid="bounds-description">{manifest.model.boundsDescription}</p>
          {grouped ? (
            <p data-testid="bounds-unavailable">
              Limites conjuntos não foram calculados para esta origem agrupada; somar os limites
              separados não produziria limites válidos.
            </p>
          ) : row.identificationBounds && row.observed > 0 ? (
            <>
              <RangeGrid
                ranges={row.identificationBounds}
                observed={row.observed}
                testId="identification-bounds"
              />
              <p className="bounds-note">
                Cada limite vale para uma célula isoladamente: os extremos não ocorrem
                necessariamente juntos e não são faixas de probabilidade.
              </p>
            </>
          ) : (
            <p data-testid="bounds-unavailable">
              Sem eleitores desta origem aqui, não há parcelas a limitar.
            </p>
          )}
        </section>
      )}
      <section className="method-explanation">
        <p className="callout">{manifest.model.status}</p>
        <h3>Estimamos a partir dos totais</h3>
        <p>
          O modelo de inferência ecológica estima fluxos compatíveis com as contagens do primeiro e
          do segundo turno. Outras trajetórias individuais também podem produzir os mesmos totais.
          Bom ajuste não identifica as escolhas de cada eleitor.
        </p>
        <h3>Como ler as cores</h3>
        <p>
          Vermelho indica uma parcela estimada maior para Lula; azul, para Flávio. A intensidade
          representa a diferença em pontos percentuais sobre toda a origem. Cinza nas barras reúne
          branco, nulo e abstenção. Áreas com hachura têm base pequena: menos de {smallBaseLimit}{' '}
          eleitores da origem escolhida.
        </p>
        <h3>Municípios</h3>
        <p data-testid="municipality-method">
          A geografia é a do local de votação no primeiro turno, não a residência do eleitor. O
          município é o nível mais detalhado publicado: seus números somam as estimativas das seções
          eleitorais dele. Quando uma origem tem menos de {smallBaseLimit} eleitores em um lugar, a
          estimativa reflete sobretudo o padrão regional do modelo.
        </p>
      </section>
      <footer className="method-footer">
        <span>Modelo: {manifest.model.label}</span>
        <span>Versão dos dados: {manifest.datasetVersion}</span>
        <p>
          Estimativas calculadas por este projeto a partir dos totais por seção do TSE
          {typeof manifest.provenance.runId === 'string'
            ? ` (execução ${manifest.provenance.runId})`
            : ''}
          . Não são votos individuais observados.
        </p>
        <div>
          <a href="https://dadosabertos.tse.jus.br/" target="_blank" rel="noreferrer">
            Dados do TSE ↗
          </a>
          <a href="https://www.ibge.gov.br/geociencias/" target="_blank" rel="noreferrer">
            Geografia do IBGE ↗
          </a>
        </div>
      </footer>
    </dialog>
  );
}
