import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {RilonoHomepagePreview} from './rilono-homepage-preview';

const Root = () => (
  <Composition
    id="RilonoHomepagePreview"
    component={RilonoHomepagePreview}
    durationInFrames={900}
    fps={30}
    width={1280}
    height={720}
  />
);

registerRoot(Root);
