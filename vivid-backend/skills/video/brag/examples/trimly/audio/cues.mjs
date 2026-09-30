// One cue table for the picture and the score.
export const BPM = 100;
export const DURATION = 13;
export const CUE = {
  nameOpen: 0,
  vo: [[0.3, 'assets/vo/vo-01.wav', 1.14], [3.3, 'assets/vo/vo-02.wav', 2.47], [10.0, 'assets/vo/vo-03.wav', 2.26]],
  morph1: 2.2,                 // "Trimly" wordmark morphs into the app's brand mark (scene 1 → 2)
  enter: 2.5,                  // app slides in with skew, screen tilted and gliding
  headline: 2.9, slots: 3.2,
  flatten: 4.2,                // tilt glide ends, screen flattens before reading
  cursor: 4.4, popOut: 5.0, press: 5.9,   // pop-out and press land after vo-02 ends (5.77)
  morph: 6.8, done: 7.5,       // button → tick
  gap: 8.6, reveal: 8.8,       // circle reveal from the tick into the lockup
  brandToName: 9.2,            // carried brand mark grows into the lockup name (scene 2 → 3)
  nameClose: 9.55, ctaGap: [9.6, 10.0],
};
