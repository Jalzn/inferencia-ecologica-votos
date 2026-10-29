import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import './onboarding.css';

const completionKey = 'elections:onboarding:v1';

function readCompletion(): boolean {
  try {
    return window.localStorage.getItem(completionKey) === 'completed';
  } catch {
    return false;
  }
}

type Layout = {
  target: { left: number; top: number; width: number; height: number };
  card: { left: number; top: number; width: number; maxHeight: number };
};

type Props = { ready: boolean; mobile: boolean; replayToken: number };

export function OnboardingGuide({ ready, mobile, replayToken }: Props) {
  const [completed, setCompleted] = useState(readCompletion);
  const [open, setOpen] = useState(false);
  const [layout, setLayout] = useState<Layout | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const card = useRef<HTMLElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const focusPending = useRef(false);
  const shown = useRef(false);
  const lastReplay = useRef(0);
  const mode = useRef<'automatic' | 'replay'>('automatic');

  useEffect(() => {
    if (!ready || completed || shown.current) return;
    const showWhenAvailable = () => {
      const target = document.getElementById('results');
      if (
        shown.current ||
        !target ||
        !target.getBoundingClientRect().width ||
        document.querySelector('dialog[open]')
      )
        return;
      shown.current = true;
      mode.current = 'automatic';
      setOpen(true);
    };
    showWhenAvailable();
    const observer = new MutationObserver(showWhenAvailable);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['open'],
    });
    return () => observer.disconnect();
  }, [ready, completed]);

  useEffect(() => {
    if (!ready || replayToken === lastReplay.current) return;
    lastReplay.current = replayToken;
    shown.current = true;
    mode.current = 'replay';
    setOpen(true);
  }, [ready, replayToken]);

  useLayoutEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      element.showModal();
      focusPending.current = true;
    } else if (!open && element.open) element.close();
    return () => {
      if (element.open) element.close();
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;
    let frame = 0;
    const measure = () => {
      const target = document.getElementById('results');
      const content = card.current;
      if (!target || !content) return;
      const bounds = target.getBoundingClientRect();
      const viewportWidth = document.documentElement.clientWidth;
      const viewportHeight = window.innerHeight;
      const left = Math.max(4, bounds.left - 6);
      const top = Math.max(4, bounds.top - 6);
      const right = Math.min(viewportWidth - 4, bounds.right + 6);
      const bottom = Math.min(viewportHeight - 4, bounds.bottom + 6);
      const width = mobile
        ? Math.min(360, viewportWidth - 32)
        : Math.min(360, Math.max(240, left - 40));
      const maxHeight = mobile ? Math.max(90, top - 32) : Math.max(90, viewportHeight - 32);
      content.style.width = `${width}px`;
      content.style.maxHeight = `${maxHeight}px`;
      const height = content.getBoundingClientRect().height;
      const next: Layout = {
        target: { left, top, width: Math.max(0, right - left), height: Math.max(0, bottom - top) },
        card: {
          left: mobile ? (viewportWidth - width) / 2 : Math.max(16, left - width - 24),
          top: mobile
            ? Math.max(16, top - height - 20)
            : Math.max(16, Math.min(top + 64, viewportHeight - height - 16)),
          width,
          maxHeight,
        },
      };
      setLayout((previous) =>
        JSON.stringify(previous) === JSON.stringify(next) ? previous : next,
      );
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    const observer = new ResizeObserver(schedule);
    const target = document.getElementById('results');
    if (target) observer.observe(target);
    if (card.current) observer.observe(card.current);
    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', schedule, true);
    window.visualViewport?.addEventListener('resize', schedule);
    window.visualViewport?.addEventListener('scroll', schedule);
    measure();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener('resize', schedule);
      window.removeEventListener('scroll', schedule, true);
      window.visualViewport?.removeEventListener('resize', schedule);
      window.visualViewport?.removeEventListener('scroll', schedule);
    };
  }, [open, mobile]);

  useLayoutEffect(() => {
    if (open && layout && focusPending.current) {
      primary.current?.focus({ preventScroll: true });
      focusPending.current = false;
    }
  }, [open, layout]);

  function dismiss(startChoosing = false) {
    setCompleted(true);
    try {
      window.localStorage.setItem(completionKey, 'completed');
    } catch {
      /* The guide still stays dismissed for this visit. */
    }
    dialog.current?.close();
    setOpen(false);
    requestAnimationFrame(() => {
      const originTarget = mobile
        ? document.getElementById('results')
        : document.querySelector<HTMLElement>('#results .origin-row[aria-pressed="true"]');
      const focusTarget =
        !startChoosing && mode.current === 'replay'
          ? document.querySelector<HTMLElement>('[data-testid="open-onboarding"]')
          : originTarget;
      focusTarget?.focus({ preventScroll: true });
      if (startChoosing && mobile && originTarget instanceof HTMLButtonElement)
        originTarget.click();
    });
  }

  return (
    <dialog
      ref={dialog}
      className="onboarding-dialog"
      data-testid="onboarding-guide"
      aria-labelledby="onboarding-title"
      aria-describedby="onboarding-description"
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
    >
      <div
        className="onboarding-spotlight"
        data-testid="onboarding-spotlight"
        aria-hidden="true"
        style={layout?.target}
      />
      <section
        ref={card}
        className="onboarding-card"
        data-testid="onboarding-card"
        data-placement={mobile ? 'above' : 'left'}
        style={{ ...layout?.card, visibility: layout ? 'visible' : 'hidden' }}
      >
        <button
          type="button"
          className="onboarding-close"
          aria-label="Fechar guia"
          onClick={() => dismiss()}
        >
          ×
        </button>
        <div className="onboarding-card-heading">
          <span className="onboarding-eyebrow">COMECE PELA ORIGEM</span>
          <h2 id="onboarding-title">Esta escolha muda o mapa</h2>
        </div>
        <div
          className="onboarding-copy"
          tabIndex={0}
          aria-label="Explicação de como a origem muda o mapa"
        >
          <div id="onboarding-description">
            <p>
              Escolha um candidato, votos brancos, nulos ou abstenção no <strong>1º turno</strong>.
            </p>
            <p>
              As cores mostram, em cada lugar, se estimamos que mais desses votos foram para Lula ou
              Flávio no <strong>2º turno</strong>.
            </p>
          </div>
          <div className="onboarding-colors" aria-hidden="true">
            <span>
              <i className="onboarding-red" />
              Mais para Lula
            </span>
            <span>
              <i className="onboarding-blue" />
              Mais para Flávio
            </span>
          </div>
          <p className="onboarding-action-hint">
            {mobile
              ? 'O botão abaixo abre as origens.'
              : 'Feche o guia pelo botão abaixo e escolha no painel destacado.'}
          </p>
        </div>
        <div className="onboarding-card-actions">
          <button
            ref={primary}
            type="button"
            className="onboarding-primary"
            data-testid="onboarding-primary"
            onClick={() => dismiss(true)}
          >
            {mobile ? 'Abrir origens' : 'Escolher uma origem'}
            <span aria-hidden="true">{mobile ? '↓' : '→'}</span>
          </button>
          <p className="onboarding-note">
            São estimativas, não o acompanhamento de votos individuais.
          </p>
        </div>
      </section>
    </dialog>
  );
}
