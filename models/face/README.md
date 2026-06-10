# Face model assets

BioAuth does not ship or download OpenCV face ONNX model binaries. The user or
release operator must manually place the official OpenCV Zoo files in this
directory when enabling local/dev Face Enrollment or Face Confirmation.

Expected filenames:

- `face_detection_yunet_2023mar.onnx`
- `face_recognition_sface_2021dec.onnx`

Backend readiness is fail-closed and project-relative:

- both files present: `models_ready`
- both files missing: `models_missing`
- detector missing: `detector_model_missing`
- recognizer missing: `recognizer_model_missing`

Do not rename the files. Do not place captured face frames, screenshots, crops,
raw camera images, embeddings, encrypted templates, logs, or other biometric
payloads in this directory.

## Runtime dependency reminder

After manually placing the two ONNX files above, install the optional face backend dependency in your local/dev environment:

```bash
python -m pip install -r requirements-face.txt
```

BioAuth still fails closed if OpenCV/cv2, camera permission, model loading, consent, or template checks are not ready.
