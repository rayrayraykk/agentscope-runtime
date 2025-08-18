# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
import time
import hashlib
import traceback
import logging

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from .base_client import BaseClient

logger = logging.getLogger(__name__)


class KubernetesClient(BaseClient):
    def __init__(self, namespace="default", kubeconfig=None):
        try:
            if kubeconfig:
                config.load_kube_config(config_file=kubeconfig)
            else:
                # Try to load in-cluster config first, then fall back to
                # kubeconfig
                try:
                    config.load_incluster_config()
                except config.ConfigException:
                    config.load_kube_config()
            self.v1 = client.CoreV1Api()
            self.namespace = namespace
            # Test connection
            self.v1.list_namespace()
            logger.debug("Kubernetes client initialized successfully")
        except Exception as e:
            raise RuntimeError(
                f"Kubernetes client initialization failed: {str(e)}\n"
                "Solutions:\n"
                "• Ensure kubectl is configured\n"
                "• Check kubeconfig file permissions\n"
                "• Verify cluster connectivity\n"
                "• For in-cluster: ensure proper RBAC permissions",
            ) from e

    def _create_pod_spec(
        self,
        image,
        name,
        ports=None,
        volumes=None,
        environment=None,
        runtime_config=None,
    ):
        """Create a Kubernetes Pod specification."""
        if runtime_config is None:
            runtime_config = {}

        container_name = name or "main-container"
        # Container specification
        container = client.V1Container(
            name=container_name,
            image=f"agentscope-registry.ap-southeast-1.cr.aliyuncs.com"
            f"/{image}",
            image_pull_policy=runtime_config.get(
                "image_pull_policy",
                "IfNotPresent",
            ),
        )

        # Configure ports
        if ports:
            container_ports = []
            for host_port, container_port_info in ports.items():
                if isinstance(container_port_info, dict):
                    container_port = container_port_info.get(
                        "container_port",
                        int(host_port),
                    )
                    protocol = container_port_info.get("protocol", "TCP")
                else:
                    container_port = (
                        int(container_port_info)
                        if isinstance(container_port_info, str)
                        else container_port_info
                    )
                    protocol = "TCP"
                container_ports.append(
                    client.V1ContainerPort(
                        container_port=container_port,
                        protocol=protocol.upper(),
                    ),
                )
            container.ports = container_ports

        # Configure environment variables
        if environment:
            env_vars = []
            for key, value in environment.items():
                env_vars.append(client.V1EnvVar(name=key, value=str(value)))
            container.env = env_vars

        # Configure volume mounts and volumes
        volume_mounts = []
        pod_volumes = []
        if volumes:
            for volume_idx, (host_path, mount_info) in enumerate(
                volumes.items(),
            ):
                if isinstance(mount_info, dict):
                    container_path = mount_info["bind"]
                    mode = mount_info.get("mode", "rw")
                else:
                    container_path = mount_info
                    mode = "rw"
                volume_name = f"vol-{volume_idx}"

                # Create volume mount
                volume_mounts.append(
                    client.V1VolumeMount(
                        name=volume_name,
                        mount_path=container_path,
                        read_only=(mode == "ro"),
                    ),
                )
                # Create host path volume
                pod_volumes.append(
                    client.V1Volume(
                        name=volume_name,
                        host_path=client.V1HostPathVolumeSource(
                            path=host_path,
                        ),
                    ),
                )

        if volume_mounts:
            container.volume_mounts = volume_mounts

        # Apply runtime config to container
        if "resources" in runtime_config:
            container.resources = client.V1ResourceRequirements(
                **runtime_config["resources"],
            )

        if "security_context" in runtime_config:
            container.security_context = client.V1SecurityContext(
                **runtime_config["security_context"],
            )

        # Pod specification
        pod_spec = client.V1PodSpec(
            containers=[container],
            restart_policy=runtime_config.get("restart_policy", "Never"),
        )

        if pod_volumes:
            pod_spec.volumes = pod_volumes

        if "node_selector" in runtime_config:
            pod_spec.node_selector = runtime_config["node_selector"]

        if "tolerations" in runtime_config:
            pod_spec.tolerations = runtime_config["tolerations"]

        # Handle image pull secrets (for ACR or other private registries)
        image_pull_secrets = runtime_config.get("image_pull_secrets", [])
        if image_pull_secrets:
            secrets = []
            for secret_name in image_pull_secrets:
                secrets.append(client.V1LocalObjectReference(name=secret_name))
            pod_spec.image_pull_secrets = secrets

        return pod_spec

    def create(
        self,
        image,
        name=None,
        ports=None,
        volumes=None,
        environment=None,
        runtime_config=None,
    ):
        """Create a new Kubernetes Pod."""
        if not name:
            name = f"pod-{hashlib.md5(image.encode()).hexdigest()[:8]}"
        try:
            # Create pod specification
            pod_spec = self._create_pod_spec(
                image,
                name,
                ports,
                volumes,
                environment,
                runtime_config,
            )
            # Create pod metadata
            metadata = client.V1ObjectMeta(
                name=name,
                namespace=self.namespace,
                labels={
                    "created-by": "kubernetes-client",
                    "app": name,
                },
            )

            # Create pod object
            pod = client.V1Pod(
                api_version="v1",
                kind="Pod",
                metadata=metadata,
                spec=pod_spec,
            )
            # Create the pod
            self.v1.create_namespaced_pod(
                namespace=self.namespace,
                body=pod,
            )
            logger.debug(
                f"Pod '{name}' created successfully in namespace "
                f"'{self.namespace}'",
            )
            return True
        except ApiException as e:
            logger.error(f"Failed to create pod '{name}': {e.reason}")
            if e.status == 409:
                logger.error(f"Pod '{name}' already exists")
            return False
        except Exception as e:
            logger.error(f"An error occurred: {e}, {traceback.format_exc()}")
            return False

    def start(self, container_id):
        """
        Start a Kubernetes Pod.
        Note: Pods start automatically upon creation in Kubernetes.
        This method verifies the pod is running or can be started.
        """
        try:
            pod = self.v1.read_namespaced_pod(
                name=container_id,
                namespace=self.namespace,
            )

            current_phase = pod.status.phase
            logger.debug(
                f"Pod '{container_id}' current phase: {current_phase}",
            )

            if current_phase in ["Running", "Pending"]:
                return True
            elif current_phase in ["Failed", "Succeeded"]:
                logger.warning(
                    f"Pod '{container_id}' is in '{current_phase}' state and "
                    f"cannot be restarted. Consider recreating it.",
                )
                return False
            else:
                logger.debug(f"Pod '{container_id}' status: {current_phase}")
                return True
        except ApiException as e:
            if e.status == 404:
                logger.error(f"Pod '{container_id}' not found")
            else:
                logger.error(f"Failed to check pod status: {e.reason}")
            return False
        except Exception as e:
            logger.error(f"An error occurred: {e}, {traceback.format_exc()}")
            return False

    def stop(self, container_id, timeout=None):
        """Stop a Kubernetes Pod by deleting it gracefully."""
        try:
            grace_period = timeout if timeout else 30
            delete_options = client.V1DeleteOptions(
                grace_period_seconds=grace_period,
            )
            self.v1.delete_namespaced_pod(
                name=container_id,
                namespace=self.namespace,
                body=delete_options,
            )
            logger.debug(
                f"Pod '{container_id}' deletion initiated with"
                f" {grace_period}s grace period",
            )
            return True
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Pod '{container_id}' not found")
                return True
            logger.error(f"Failed to delete pod: {e.reason}")
            return False
        except Exception as e:
            logger.error(f"An error occurred: {e}, {traceback.format_exc()}")
            return False

    def remove(self, container_id, force=False):
        """Remove a Kubernetes Pod."""
        try:
            delete_options = client.V1DeleteOptions()

            if force:
                delete_options.grace_period_seconds = 0
                delete_options.propagation_policy = "Background"
            self.v1.delete_namespaced_pod(
                name=container_id,
                namespace=self.namespace,
                body=delete_options,
            )
            logger.debug(
                f"Pod '{container_id}' removed"
                f" {'forcefully' if force else 'gracefully'}",
            )
            return True
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Pod '{container_id}' not found")
                return True
            logger.error(f"Failed to remove pod: {e.reason}")
            return False
        except Exception as e:
            logger.error(f"An error occurred: {e}, {traceback.format_exc()}")
            return False

    def inspect(self, container_id):
        """Inspect a Kubernetes Pod."""
        try:
            pod = self.v1.read_namespaced_pod(
                name=container_id,
                namespace=self.namespace,
            )
            return pod.to_dict()
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Pod '{container_id}' not found")
            else:
                logger.error(f"Failed to inspect pod: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"An error occurred: {e}, {traceback.format_exc()}")
            return None

    def get_status(self, container_id):
        """Get the current status of the specified pod."""
        pod_info = self.inspect(container_id)
        if pod_info and "status" in pod_info:
            return pod_info["status"]["phase"]
        return None

    def get_logs(
        self,
        container_id,
        container_name=None,
        tail_lines=None,
        follow=False,
    ):
        """Get logs from a pod."""
        try:
            logs = self.v1.read_namespaced_pod_log(
                name=container_id,
                namespace=self.namespace,
                container=container_name,
                tail_lines=tail_lines,
                follow=follow,
            )
            return logs
        except ApiException as e:
            logger.error(
                f"Failed to get logs from pod '{container_id}': {e.reason}",
            )
            return None
        except Exception as e:
            logger.error(f"An error occurred: {e}, {traceback.format_exc()}")
            return None

    def list_pods(self, label_selector=None):
        """List pods in the namespace."""
        try:
            pods = self.v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=label_selector,
            )
            return [pod.metadata.name for pod in pods.items]
        except ApiException as e:
            logger.error(f"Failed to list pods: {e.reason}")
            return []
        except Exception as e:
            logger.error(f"An error occurred: {e}, {traceback.format_exc()}")
            return []

    def wait_for_pod_ready(self, container_id, timeout=300):
        """Wait for a pod to be ready."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                pod = self.v1.read_namespaced_pod(
                    name=container_id,
                    namespace=self.namespace,
                )
                print(pod.status.phase)
                if pod.status.phase == "Running":
                    # Check if all containers are ready
                    if pod.status.container_statuses:
                        all_ready = all(
                            container.ready
                            for container in pod.status.container_statuses
                        )
                        if all_ready:
                            return True
                elif pod.status.phase in ["Failed", "Succeeded"]:
                    return False
                time.sleep(2)
            except ApiException as e:
                if e.status == 404:
                    return False
                time.sleep(2)
        return False

    def create_service(
        self,
        container_id,
        port,
        target_port=None,
        service_type="NodePort",
    ):
        """Create service to expose node"""
        try:
            if target_port is None:
                target_port = port
            selector = {"app": container_id}

            service_spec = client.V1ServiceSpec(
                selector=selector,
                ports=[
                    client.V1ServicePort(
                        port=port,
                        target_port=target_port,
                        protocol="TCP",
                    ),
                ],
                type=service_type,
            )
            service = client.V1Service(
                api_version="v1",
                kind="Service",
                metadata=client.V1ObjectMeta(name=f"{container_id}-service"),
                spec=service_spec,
            )

            self.v1.create_namespaced_service(
                namespace=self.namespace,
                body=service,
            )

            logger.info(
                f"Service '{container_id}-service' created successfully.",
            )

            # Wait a second
            time.sleep(1)
            service_info = self.v1.read_namespaced_service(
                name=f"{container_id}-service",
                namespace=self.namespace,
            )

            if service_type == "NodePort":
                node_port = service_info.spec.ports[0].node_port
                print(f"Service exposed on NodePort: {node_port}")
            return True
        except Exception as e:
            logger.error(f"Failed to create service: {e}")
            return False

    def get_service_url(self, container_id):
        """Get the node port"""
        try:
            service_info = self.v1.read_namespaced_service(
                name=f"{container_id}-service",
                namespace=self.namespace,
            )
            if service_info.spec.type == "NodePort":
                node_port = service_info.spec.ports[0].node_port
                return f"http://localhost:{node_port}"

            return None

        except Exception as e:
            logger.error(f"Failed to get service URL: {e}")
            return None
