import { ImageResponse } from 'next/og'

export const runtime = 'edge'
export const alt = 'Volt Query AI - AI-Powered EV & Energy Insights'
export const size = {
  width: 1200,
  height: 630,
}
export const contentType = 'image/png'

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          fontSize: 128,
          background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)',
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'white',
          padding: '40px',
        }}
      >
        <div style={{ fontSize: 120, marginBottom: 20 }}>⚡</div>
        <div style={{ fontSize: 64, fontWeight: 'bold', marginBottom: 20 }}>
          Volt Query AI
        </div>
        <div style={{ fontSize: 32, color: '#94a3b8', textAlign: 'center' }}>
          AI-powered insights for EV charging, electricity rates, solar energy, and energy optimization
        </div>
      </div>
    ),
    {
      ...size,
    }
  )
}

