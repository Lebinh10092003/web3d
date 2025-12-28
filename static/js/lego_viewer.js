const THREE_CDN = "https://cdn.jsdelivr.net/npm/three@0.160.0";
const MODULES = {
  three: `${THREE_CDN}/build/three.module.js`,
  orbitControls: `${THREE_CDN}/examples/jsm/controls/OrbitControls.js`,
  ldrawLoader: `${THREE_CDN}/examples/jsm/loaders/LDrawLoader.js`,
};

const CANVAS_DEFAULT_HEIGHT = 420;
globalThis.__legoViewerLoaded = true;

let threeDepsPromise = null;

async function loadThreeDeps() {
  if (!threeDepsPromise) {
    threeDepsPromise = (async () => {
      const [THREE, orbitModule, ldrawModule] = await Promise.all([
        import(MODULES.three),
        import(MODULES.orbitControls),
        import(MODULES.ldrawLoader),
      ]);
      return {
        THREE,
        OrbitControls: orbitModule.OrbitControls,
        LDrawLoader: ldrawModule.LDrawLoader,
      };
    })();
  }
  return threeDepsPromise;
}

function ensureTrailingSlash(value) {
  if (!value) {
    return "/";
  }
  return value.endsWith("/") ? value : `${value}/`;
}

function setStatus(node, message, level = "") {
  if (!node) {
    return;
  }
  node.textContent = message;
  node.dataset.level = level;
}

function fitCamera(THREE, camera, controls, object, offset = 1.25) {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) {
    return null;
  }
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z);
  const fitHeightDistance = maxDim / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
  const fitWidthDistance = fitHeightDistance / camera.aspect;
  const distance = offset * Math.max(fitHeightDistance, fitWidthDistance);

  const direction = controls.target
    .clone()
    .sub(camera.position)
    .normalize()
    .multiplyScalar(distance);

  camera.near = Math.max(0.1, distance / 200);
  camera.far = Math.max(1000, distance * 20);
  camera.updateProjectionMatrix();

  controls.target.copy(center);
  camera.position.copy(controls.target).sub(direction);
  controls.update();
  return { center, distance };
}

function setRendererSize(renderer, canvas, camera) {
  const width = canvas.clientWidth || canvas.parentElement?.clientWidth || 1;
  const height = canvas.clientHeight || CANVAS_DEFAULT_HEIGHT;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function buildScene(THREE) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xffffff);

  const ambient = new THREE.AmbientLight(0xffffff, 0.75);
  scene.add(ambient);

  const directional = new THREE.DirectionalLight(0xffffff, 0.9);
  directional.position.set(200, 400, 300);
  scene.add(directional);

  const grid = new THREE.GridHelper(400, 40, 0x9aa0a6, 0xdadce0);
  grid.material.transparent = true;
  grid.material.opacity = 0.3;
  scene.add(grid);

  return scene;
}

async function initViewer(root) {
  if (!root || root.dataset.legoBound === "true") {
    return;
  }

  const canvas = root.querySelector("[data-lego-canvas]");
  const status = root.querySelector("[data-lego-status]");
  const fitButton = root.querySelector("[data-lego-fit]");
  const resetButton = root.querySelector("[data-lego-reset]");

  const modelUrl = root.dataset.modelUrl;
  const partsPath = ensureTrailingSlash(root.dataset.partsPath);

  if (!canvas || !modelUrl) {
    setStatus(status, "Missing 3D model source.", "error");
    return;
  }

  try {
    root.dataset.legoBound = "true";
    setStatus(status, "Loading 3D viewer…", "loading");

  const { THREE, OrbitControls, LDrawLoader } = await loadThreeDeps();

    if (!canvas.style.height) {
      canvas.style.height = `${CANVAS_DEFAULT_HEIGHT}px`;
    }

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    const scene = buildScene(THREE);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    camera.position.set(320, 260, 320);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 0.7;

    setRendererSize(renderer, canvas, camera);

    const onResize = () => setRendererSize(renderer, canvas, camera);
    let resizeObserver = null;
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(onResize);
      resizeObserver.observe(root);
    } else {
      window.addEventListener("resize", onResize);
    }

    let modelGroup = null;
    let initialCamera = null;

    const loader = new LDrawLoader();
    loader.setPartsLibraryPath(partsPath);

    setStatus(status, "Loading 3D model…", "loading");

    loader.load(
      modelUrl,
    (group) => {
      modelGroup = group;
      scene.add(group);
      fitCamera(THREE, camera, controls, group);
      initialCamera = {
        position: camera.position.clone(),
        target: controls.target.clone(),
      };
      setStatus(status, "", "");
    },
      (event) => {
        if (!event || !event.total) {
          return;
        }
        const percent = Math.min(
          100,
          Math.round((event.loaded / event.total) * 100)
        );
        setStatus(status, `Loading 3D model… ${percent}%`, "loading");
      },
      () => {
        setStatus(
          status,
          "Could not load 3D model. Check the uploaded file format.",
          "error"
        );
      }
    );

    if (fitButton) {
      fitButton.addEventListener("click", () => {
        if (!modelGroup) {
          return;
        }
        fitCamera(THREE, camera, controls, modelGroup);
      });
    }

    if (resetButton) {
      resetButton.addEventListener("click", () => {
        if (!initialCamera) {
          return;
        }
        camera.position.copy(initialCamera.position);
        controls.target.copy(initialCamera.target);
        controls.update();
      });
    }

    function animate() {
      if (!root.isConnected) {
        resizeObserver?.disconnect?.();
        window.removeEventListener("resize", onResize);
        renderer.dispose();
        return;
      }
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }

    animate();
  } catch (error) {
    console.error("LEGO viewer failed to initialize", error);
    setStatus(
      status,
      "Không tải được thư viện Three.js (module). Kiểm tra mạng/CDN (cdn.jsdelivr.net) hoặc mở Console để xem lỗi.",
      "error"
    );
  }
}

function initAll() {
  document.querySelectorAll("[data-lego-viewer]").forEach((root) => {
    initViewer(root);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAll, { once: true });
} else {
  initAll();
}

document.body?.addEventListener?.("htmx:afterSwap", initAll);
