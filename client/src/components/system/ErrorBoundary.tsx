import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props { children: ReactNode }
interface State { error: Error | null }

/** Last-resort boundary: paints the crash on screen instead of a silent blank void. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('[error-boundary]', error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div style={{ minHeight: '100vh', background: '#07090d', color: '#e8eef5', padding: 24, fontFamily: 'monospace' }}>
        <p style={{ color: '#FF6B35', letterSpacing: 2, textTransform: 'uppercase', fontSize: 11, marginBottom: 8 }}>
          UI crashed — renderer error (press Ctrl+Shift+I for the full stack)
        </p>
        <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', color: '#8CA0B3' }}>{String(error.stack ?? error.message)}</pre>
        <button
          onClick={() => { this.setState({ error: null }); window.location.reload(); }}
          style={{ marginTop: 16, padding: '6px 14px', background: '#FF6B35', color: '#07090d', border: 'none', cursor: 'pointer', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: 2, fontSize: 11 }}
        >
          reload
        </button>
      </div>
    );
  }
}