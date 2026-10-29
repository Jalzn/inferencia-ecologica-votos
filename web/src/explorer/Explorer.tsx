import { useEffect, useMemo, useRef, useState } from 'react';
import { DatasetClient } from '../data/client';
import { bundleIdForPlace } from '../data/places';
import type { AreaBundle, Manifest, SearchPlace, Selection } from '../data/types';
import { ElectionMap } from '../map/ElectionMap';
import { MethodDialog } from '../methodology/MethodDialog';
import { OnboardingGuide } from '../onboarding/OnboardingGuide';
import { OriginPanel } from '../results/OriginPanel';
import { MobileOriginSheet } from '../results/MobileOriginSheet';
import { useMediaQuery } from '../shared/useMediaQuery';
import {
  hasAssociatedSections,
  isSmallBase,
  readSelection,
  selectionQuery,
  summarize,
} from '../results/model';
import { smallBaseNote } from '../results/copy';
import { GeographicSearch } from '../search/GeographicSearch';

const client = new DatasetClient(
  new URL(`${import.meta.env.BASE_URL}data/`, window.location.origin),
);
const stateNames: Record<string, string> = {
  AC: 'Acre',
  AL: 'Alagoas',
  AP: 'Amapá',
  AM: 'Amazonas',
  BA: 'Bahia',
  CE: 'Ceará',
  DF: 'Distrito Federal',
  ES: 'Espírito Santo',
  GO: 'Goiás',
  MA: 'Maranhão',
  MT: 'Mato Grosso',
  MS: 'Mato Grosso do Sul',
  MG: 'Minas Gerais',
  PA: 'Pará',
  PB: 'Paraíba',
  PR: 'Paraná',
  PE: 'Pernambuco',
  PI: 'Piauí',
  RJ: 'Rio de Janeiro',
  RN: 'Rio Grande do Norte',
  RS: 'Rio Grande do Sul',
  RO: 'Rondônia',
  RR: 'Roraima',
  SC: 'Santa Catarina',
  SP: 'São Paulo',
  SE: 'Sergipe',
  TO: 'Tocantins',
  ZZ: 'Exterior',
};

export function Explorer() {
  const mobile = useMediaQuery('(max-width: 700px)');
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [index, setIndex] = useState<SearchPlace[]>([]);
  const [selection, setSelection] = useState<Selection>(() => readSelection());
  const [bundle, setBundle] = useState<AreaBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchRetry, setSearchRetry] = useState(0);
  const [retry, setRetry] = useState(0);
  const [dialogMode, setDialogMode] = useState<'method' | 'detail' | null>(null);
  const [shareMessage, setShareMessage] = useState('');
  const [onboardingReplay, setOnboardingReplay] = useState(0);
  const loadSequence = useRef(0);

  useEffect(() => {
    // The release is immutable: retry a failed bundle without fetching its catalog again.
    if (manifest) return;
    const controller = new AbortController();
    client
      .manifest(controller.signal)
      .then((release) => setManifest(release))
      .catch((reason) => {
        if (reason.name !== 'AbortError') {
          setError(reason.message);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [manifest, retry]);

  // The search index is independent of map bundles: its failure must not block or be cleared
  // by them, and it can be retried on its own.
  useEffect(() => {
    if (!manifest) return;
    const controller = new AbortController();
    setSearchError(null);
    client
      .search(manifest, controller.signal)
      .then((search) => setIndex(search.places))
      .catch((reason) => {
        if (reason.name !== 'AbortError') setSearchError(reason.message);
      });
    return () => controller.abort();
  }, [manifest, searchRetry]);

  useEffect(() => {
    const pop = () => {
      setSelection(readSelection());
      setDialogMode(null);
    };
    window.addEventListener('popstate', pop);
    return () => window.removeEventListener('popstate', pop);
  }, []);

  // Municipalities are children of their state bundle: selecting one inside the loaded state
  // bundle neither fetches nor locks the map.
  const bundleKey = bundleIdForPlace(selection.place) ?? selection.place;
  useEffect(() => {
    if (!manifest) return;
    const sequence = ++loadSequence.current;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    client
      .bundle(manifest, bundleKey, controller.signal)
      .then((data) => {
        if (sequence !== loadSequence.current) return;
        setBundle(data);
        setLoading(false);
      })
      .catch((reason) => {
        if (reason.name !== 'AbortError' && sequence === loadSequence.current) {
          setError(reason.message);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [manifest, bundleKey, retry]); // Origin and same-bundle place changes do not fetch again.

  function navigate(patch: Partial<Selection>, replace = false) {
    const next = { ...selection, ...patch };
    if (next.place === selection.place && next.origin === selection.origin) return;
    if (bundleIdForPlace(next.place) !== bundleKey) setLoading(true);
    window.history[replace ? 'replaceState' : 'pushState'](null, '', selectionQuery(next));
    setSelection(next);
    setDialogMode(null);
  }
  function selectPlace(id: string) {
    navigate({ place: id });
  }
  function zoomNavigate(id: string): boolean {
    if (!manifest || loading || id === selection.place || !client.available(manifest, id))
      return false;
    selectPlace(id);
    return true;
  }
  const requested =
    bundle &&
    (bundle.place.id === selection.place
      ? bundle.place
      : bundle.children.find((place) => place.id === selection.place));
  const selected = requested || bundle?.place || null;
  // A same-bundle link (for example, history) can name a child absent from this release.
  const missingPlace = !loading && !!bundle && bundle.id === bundleKey && !requested;
  const failure =
    error ||
    (missingPlace ? 'O lugar deste link não foi encontrado nesta versão dos dados.' : null);
  const group =
    manifest &&
    (manifest.displayGroups.find((item) => item.id === selection.origin) ||
      manifest.displayGroups[0]);
  useEffect(() => {
    if (loading || failure || !bundle || !group) return;
    const canonical = { ...selection, origin: group.id };
    const query = selectionQuery(canonical);
    // Rewrites unknown origins and extra query parameters into the canonical link.
    if (
      canonical.origin !== selection.origin ||
      (window.location.search && window.location.search !== query)
    )
      window.history.replaceState(null, '', query);
    if (canonical.origin !== selection.origin) setSelection(canonical);
  }, [loading, failure, bundle, group, selection]);
  const title = selected?.id === 'BR' ? 'Brasil' : selected?.name;
  const currentState = selected?.stateCode || 'BR';
  const isChild = !!selected && !!bundle && selected.id !== bundle.place.id;
  // Map legend keys describe only the areas drawn on the map.
  const mapKeys = useMemo(() => {
    if (!bundle || !group) return { smallBase: false, noSections: false };
    const drawn = new Set(
      (bundle.geometry[bundle.defaultLayer]?.features ?? []).map((feature) =>
        String(feature.properties?.id),
      ),
    );
    const children = bundle.children.filter((place) => drawn.has(place.id));
    return {
      smallBase: children.some((place) => isSmallBase(summarize(place, group).observed)),
      noSections: children.some((place) => !hasAssociatedSections(place)),
    };
  }, [bundle, group]);
  const shareLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setShareMessage('Link copiado');
    } catch {
      setShareMessage('Copie o endereço desta página');
    }
    window.setTimeout(() => setShareMessage(''), 3500);
  };

  return (
    <>
      <main className="page-shell">
        <a className="skip-link" href="#results">
          Ir para estimativas
        </a>
        {manifest?.scope === 'fixture' && (
          <div className="fixture-banner" role="status">
            <strong>Amostra de desenvolvimento.</strong> Dados reais com cobertura parcial. A
            publicação completa inclui todo o Brasil.
          </div>
        )}
        {failure && (
          <div className="error-panel" role="alert">
            <strong>Não foi possível abrir esta seleção.</strong>
            <p>{failure}</p>
            <div>
              <button onClick={() => setRetry((value) => value + 1)}>Tentar novamente</button>
              <button onClick={() => navigate({ place: 'BR' })}>Voltar ao Brasil</button>
            </div>
          </div>
        )}
        {!bundle && !failure && (
          <div className="initial-loading" role="status">
            <span className="loading-orbit" />
            <h1>Preparando os caminhos do voto</h1>
            <p>Carregando dados e conferindo sua integridade.</p>
          </div>
        )}
        {bundle && selected && group && manifest && (
          <div className={`workspace ${loading ? 'is-loading' : ''}`} aria-busy={loading}>
            <section className="map-card" aria-label="Explorador geográfico">
              <div className="navigation-bar">
                <nav aria-label="Localização selecionada" className="breadcrumbs">
                  <button
                    onClick={() => navigate({ place: 'BR' })}
                    aria-current={selection.place === 'BR' ? 'location' : undefined}
                  >
                    Brasil
                  </button>
                  {currentState !== 'BR' && (
                    <>
                      <span aria-hidden="true">/</span>
                      <button
                        onClick={() => navigate({ place: currentState })}
                        aria-current={selection.place === currentState ? 'location' : undefined}
                      >
                        {stateNames[currentState] || currentState}
                      </button>
                    </>
                  )}
                  {isChild && bundle.level === 'state' && (
                    <>
                      <span aria-hidden="true">/</span>
                      <span className="current-crumb" aria-current="location">
                        {selected.name}
                      </span>
                    </>
                  )}
                </nav>
                <div className="navigation-tools">
                  <GeographicSearch
                    places={index}
                    available={(id) => !!manifest && client.available(manifest, id)}
                    onSelect={selectPlace}
                  />
                  {searchError && (
                    <p className="search-error" role="alert" data-testid="search-error">
                      Busca indisponível.{' '}
                      <button type="button" onClick={() => setSearchRetry((value) => value + 1)}>
                        Tentar de novo
                      </button>
                    </p>
                  )}
                  <button
                    className="share-button"
                    type="button"
                    onClick={shareLink}
                    aria-label="Copiar link desta seleção"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path
                        d="M9 15 15 9M7.5 16.5l-1 1a3.5 3.5 0 0 1-5-5l4-4a3.5 3.5 0 0 1 5 0M16.5 7.5l1-1a3.5 3.5 0 0 1 5 5l-4 4a3.5 3.5 0 0 1-5 0"
                        transform="translate(0 -1) scale(.95)"
                      />
                    </svg>
                  </button>
                  <button
                    type="button"
                    className="method-button"
                    data-testid="open-method"
                    onClick={() => setDialogMode('method')}
                    disabled={!selected}
                  >
                    Como estimamos
                  </button>
                  <span className="share-feedback" role="status">
                    {shareMessage}
                  </span>
                  <button
                    type="button"
                    className="onboarding-replay"
                    data-testid="open-onboarding"
                    aria-label="Como usar o mapa"
                    title="Como usar o mapa"
                    disabled={loading || !selected}
                    onClick={() => setOnboardingReplay((value) => value + 1)}
                  >
                    <span aria-hidden="true">?</span>
                  </button>
                </div>
              </div>

              <div className="map-heading">
                <div>
                  <h1 data-testid="place-title">{title}</h1>
                  <p className="map-subtitle">
                    Origem no 1º turno: <strong>{group.label}</strong>
                  </p>
                </div>
              </div>
              <ElectionMap
                bundle={bundle}
                selected={selected}
                group={group}
                onSelect={selectPlace}
                onZoomNavigate={zoomNavigate}
                zoomNavigationEnabled={!loading}
                requestedPlaceId={failure ? bundle.id : selection.place}
                available={(id) => client.available(manifest, id)}
              />
              <div className="map-footer">
                <span className="map-attribution" title={bundle.sourceLabel}>
                  TSE · IBGE
                </span>
                <div
                  className="map-legend"
                  role="img"
                  aria-label="Diferença entre as parcelas estimadas para Lula e Flávio, em pontos percentuais sobre toda a origem selecionada"
                  title="Lula menos Flávio, em pontos percentuais sobre o total da origem selecionada"
                >
                  <div>
                    <span>
                      <i className="dot red" />
                      Mais Lula
                    </span>
                    <span>Equilíbrio</span>
                    <span>
                      Mais Flávio
                      <i className="dot blue" />
                    </span>
                  </div>
                  <div className="legend-gradient" />
                  <div className="legend-values">
                    <span>+100 p.p.</span>
                    <span>Lula − Flávio, em p.p.</span>
                    <span>−100 p.p.</span>
                  </div>
                </div>
                <div className="map-missing-keys">
                  {mapKeys.smallBase && (
                    <span
                      className="absent-key small-base-key"
                      data-testid="small-base-key"
                      title={smallBaseNote}
                    >
                      <i />
                      Base pequena (&lt;100)
                    </span>
                  )}
                  <span className="absent-key">
                    <i />
                    Origem ausente
                  </span>
                  {mapKeys.noSections && (
                    <span className="absent-key no-sections-key">
                      <i />
                      Sem seções associadas
                    </span>
                  )}
                </div>
              </div>
            </section>
            {mobile ? (
              <MobileOriginSheet
                manifest={manifest}
                place={selected}
                selectedGroup={group}
                onSelect={(origin) => navigate({ origin })}
                onDetails={() => setDialogMode('detail')}
              />
            ) : (
              <div id="results">
                <OriginPanel
                  manifest={manifest}
                  place={selected}
                  selectedGroup={group}
                  onSelect={(origin) => navigate({ origin })}
                  onDetails={() => setDialogMode('detail')}
                />
              </div>
            )}
          </div>
        )}
      </main>
      {loading && bundle && (
        <div className="loading-toast" role="status">
          <span className="loading-dot" />
          Abrindo seleção…
        </div>
      )}
      {manifest && selected && group && (
        <MethodDialog
          open={dialogMode !== null}
          mode={dialogMode || 'method'}
          onClose={() => setDialogMode(null)}
          manifest={manifest}
          place={selected}
          group={group}
          row={summarize(selected, group)}
        />
      )}
      <OnboardingGuide
        ready={!!manifest && !!bundle && !!selected && !loading && !failure && dialogMode === null}
        mobile={mobile}
        replayToken={onboardingReplay}
      />
    </>
  );
}
