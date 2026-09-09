/** Temporal scrubber: drag to window the 14-day lookback; play slides it forward. */
import { useEffect, useRef } from 'react';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Slider from '@mui/material/Slider';
import Typography from '@mui/material/Typography';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import RefreshIcon from '@mui/icons-material/Refresh';
import { WINDOW_BOUNDS, useAnalyticsStore } from '@/store/useAnalyticsStore';
import { dayLabel } from '@/lib/utils/format';

const TICK_MS = 500;

export function TimeSlider() {
  const timeRange = useAnalyticsStore((s) => s.timeRange);
  const setTimeRange = useAnalyticsStore((s) => s.setTimeRange);
  const play = useAnalyticsStore((s) => s.play);
  const pause = useAnalyticsStore((s) => s.pause);
  const resetTimeRange = useAnalyticsStore((s) => s.resetTimeRange);
  const tick = useAnalyticsStore((s) => s.tick);
  const intervalRef = useRef<number | null>(null);

  useEffect(() => {
    if (timeRange.playing) {
      intervalRef.current = window.setInterval(tick, TICK_MS);
    }
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [timeRange.playing, tick]);

  const rangeDays = Math.round((timeRange.end - timeRange.start) / 86_400_000);

  return (
    <Box sx={{
      position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)',
      width: '60%', maxWidth: 760, bgcolor: 'rgba(14, 20, 27, 0.95)', border: '1px solid #1D2833',
      borderRadius: 1, p: 2, backdropFilter: 'blur(8px)', zIndex: 5,
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography className="mono" sx={{ fontSize: 10, color: '#8CA0B3', textTransform: 'uppercase', letterSpacing: '0.16em' }}>
          temporal scrubber · near-real-time (FIRMS 3–6 h latency)
        </Typography>
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <IconButton size="small" onClick={() => (timeRange.playing ? pause() : play())}
            aria-label={timeRange.playing ? 'Pause scrubbing' : 'Play scrubbing'} sx={{ color: '#FF6B35' }}>
            {timeRange.playing ? <PauseIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
          </IconButton>
          <IconButton size="small" onClick={resetTimeRange} aria-label="Reset scrubber" sx={{ color: '#8CA0B3' }}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Box>
      </Box>

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography className="mono" sx={{ fontSize: 10, color: '#E8EEF5' }}>{dayLabel(timeRange.start)}</Typography>
        <Typography className="mono" sx={{ fontSize: 10, color: '#E8EEF5' }}>{dayLabel(timeRange.end)}</Typography>
      </Box>

      <Slider
        value={[timeRange.start, timeRange.end]}
        min={WINDOW_BOUNDS.min}
        max={WINDOW_BOUNDS.max}
        step={3_600_000}
        onChange={(_, v) => {
          const [s, e] = v as [number, number];
          if (e - s >= 3_600_000) setTimeRange({ start: s, end: e });
        }}
        valueLabelDisplay="off"
        disableSwap
        sx={{ color: '#FF6B35', '& .MuiSlider-thumb': { width: 12, height: 12, '&:hover': { boxShadow: '0 0 0 8px rgba(255, 107, 53, 0.16)' } } }}
      />

      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 1 }}>
        <Typography className="mono" sx={{ fontSize: 11, color: '#FFB800' }}>
          {rangeDays}d window · {timeRange.speed}x playback
        </Typography>
      </Box>
    </Box>
  );
}
