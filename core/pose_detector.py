import cv2
import mediapipe as mp


class PoseDetector:
    def __init__(self):
        self._mp_pose = mp.solutions.pose
        self._mp_drawing = mp.solutions.drawing_utils
        self._pose = self._mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            smooth_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmark_spec = self._mp_drawing.DrawingSpec(
            color=(0, 255, 100), thickness=2, circle_radius=4
        )
        self._connection_spec = self._mp_drawing.DrawingSpec(
            color=(0, 180, 255), thickness=2
        )

    def process(self, bgr_frame):
        """
        Run pose detection on a BGR frame.

        Returns
        -------
        landmarks : list or None
            mediapipe NormalizedLandmark list (33 entries), or None if no pose found.
        annotated : ndarray
            Copy of the frame with pose skeleton drawn on it.
        """
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        results = self._pose.process(rgb)

        annotated = bgr_frame.copy()
        if results.pose_landmarks:
            self._mp_drawing.draw_landmarks(
                annotated,
                results.pose_landmarks,
                self._mp_pose.POSE_CONNECTIONS,
                landmark_drawing_spec=self._landmark_spec,
                connection_drawing_spec=self._connection_spec,
            )
            return results.pose_landmarks.landmark, annotated

        return None, annotated

    def close(self):
        self._pose.close()
