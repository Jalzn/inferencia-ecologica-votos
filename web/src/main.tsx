import '@fontsource-variable/dm-sans';
import '@fontsource-variable/manrope';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Explorer } from './explorer/Explorer';
import './shared/styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Explorer />
  </StrictMode>,
);
