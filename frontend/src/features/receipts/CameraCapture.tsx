import { useEffect, useRef, useState } from "react";
import { Icon } from "../../components/Icon";

interface CameraCaptureProps {
  onCapture: (file: File) => void;
  onClose: () => void;
}

export function CameraCapture({ onCapture, onClose }: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [cameraCycle, setCameraCycle] = useState(0);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setCameraReady(false);
    setError(null);

    async function startCamera() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("This browser does not expose a camera. Use the upload fallback instead.");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1600 }, height: { ideal: 1200 } },
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
          setCameraReady(true);
        }
      } catch {
        setError("Camera access was unavailable. Check browser permission or use the upload fallback.");
      }
    }

    void startCamera();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, [cameraCycle]);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  function capture() {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0 || video.videoHeight === 0) return;
    const maxWidth = 1600;
    const scale = Math.min(1, maxWidth / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const context = canvas.getContext("2d");
    if (!context) return;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) {
        setError("The photo could not be prepared. Please try again.");
        return;
      }
      const file = new File([blob], `receipt-${new Date().toISOString().replace(/[:.]/g, "-")}.jpg`, { type: "image/jpeg" });
      setCapturedFile(file);
      setPreviewUrl(URL.createObjectURL(file));
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setCameraReady(false);
    }, "image/jpeg", 0.84);
  }

  function retake() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setCapturedFile(null);
    setCameraCycle((cycle) => cycle + 1);
  }

  function chooseUpload(file: File | undefined) {
    if (file) onCapture(file);
  }

  return (
    <div className="camera-capture-backdrop" role="dialog" aria-modal="true" aria-labelledby="camera-capture-title">
      <section className="camera-capture-panel">
        <header className="camera-capture-header">
          <div><span className="field-label">Receipt capture</span><h2 id="camera-capture-title">Frame the whole receipt</h2><p>Keep the paper flat, bright, and inside the guide.</p></div>
          <button type="button" className="icon-button" aria-label="Close camera" onClick={onClose}><Icon name="close" size={21} /></button>
        </header>
        <div className="camera-stage">
          {previewUrl ? <img src={previewUrl} alt="Captured receipt preview" /> : <video ref={videoRef} playsInline muted aria-label="Live receipt camera preview" />}
          <div className="camera-guide" aria-hidden="true" />
          {!previewUrl && !cameraReady && !error ? <div className="camera-stage-message">Starting camera…</div> : null}
        </div>
        {error ? <div className="camera-error" role="status"><Icon name="refresh" size={17} />{error}</div> : null}
        <div className="camera-capture-actions">
          {previewUrl && capturedFile ? <>
            <button type="button" className="button button-secondary" onClick={retake}><Icon name="refresh" size={18} />Retake</button>
            <button type="button" className="button button-primary" onClick={() => onCapture(capturedFile)}><Icon name="check" size={18} />Use this photo</button>
          </> : <button type="button" className="button button-primary" disabled={!cameraReady} onClick={capture}><Icon name="camera" size={18} />Capture photo</button>}
          <label className="button button-quiet-danger upload-button"><Icon name="upload" size={18} />Use a file<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => { chooseUpload(event.target.files?.[0]); event.currentTarget.value = ""; }} /></label>
        </div>
      </section>
    </div>
  );
}
